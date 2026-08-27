const mysql = require('mysql');
const moment = require('moment');
const { parseISO, differenceInMinutes, isValid } = require('date-fns');

// Import the new Redis handler and connection closer
const { getLTP, closeRedisConnection } = require('./readhandler');

const today = moment().format('YYYY-MM-DD');

// --- Configuration ---
// Max age of an LTP tick before it is considered stale (covers entire 15:25-15:35 window)
const MAX_LTP_AGE_MINUTES = 15;

// --- MySQL Configuration ---
const mysqlConfig = {
  host: 'localhost',
  user: 'root',
  password: 'root',
  database: 'markets'
};

// Create a MySQL Connection Pool
const pool = mysql.createPool(mysqlConfig);

// --- Main Execution Logic ---
(async () => {
    const isFutureValue = 'OPTIONS';
    const priceCheckMode = process.argv[3];
    const orderTypeArg = process.argv[4] ? process.argv[4].toLowerCase() : 'market';
    
    // 🟢 NEW: Array to collect successful orders for summary table
    const successfulOrders = [];

    if (!isFutureValue || !priceCheckMode) {
        console.error("Error: Both 'is_future' and 'priceCheckMode' arguments are required.");
        pool.end();
        closeRedisConnection();
        return;
    }
    console.log(`Starting orchestrator with mode: ${priceCheckMode} and is_future: ${isFutureValue}`);

    // RESTORED: AMO_nocheck logic
    const isAmoMode = priceCheckMode === 'AMO_nocheck';
    const tableName = 'orders_option'; // OPTIONS ORCHESTRATOR
    const originalPriceColumnName = isAmoMode ? 'buy_price' : 'price';

    try {
        let orderStocks;
        
        // 🚨 Order Selection Logic: Reading orders based on priceCheckMode
        if (priceCheckMode === 'WatchMarketAndPlace-Options_Pair' || priceCheckMode === 'Exit-Options_Pair' || priceCheckMode === 'Entry-Options_Pair') {
             console.log(`Special mode: ${priceCheckMode}. Reading all orders to sequence BUY then SELL.`);
            orderStocks = await executeQueryInSQL(
                `SELECT * FROM ${tableName} WHERE simulationtime = ? AND is_future = ?`,
                [today, isFutureValue]
            );
        }
        else if (priceCheckMode === 'withoutpricecheck') {
             console.log(`Special mode: ${priceCheckMode}. Reading all orders regardless of 'isvalid' status.`);
            orderStocks = await executeQueryInSQL(
                `SELECT * FROM ${tableName} WHERE simulationtime = ? AND is_future = ?`,
                [today, isFutureValue]
            );
        }
        else {
            // Original query for remaining modes (TL_sell_withpricecheck_greaterthan, AMO_nocheck)
            orderStocks = await executeQueryInSQL(
                `SELECT * FROM ${tableName} WHERE simulationtime = ? AND is_future = ? AND isvalid != 'FALSE'`,
                [today, isFutureValue]
            );
        }

        if (orderStocks.length === 0) {
            console.log("No valid orders to process.");
            return;
        }

        // Set to track UNIQUE combinations of 'stockname:user' for which a BUY order has already been marked TRUE
        const executedUserStocks = new Set();

        // --- START NEW CODE BLOCK ---
        // NEW: Set to track stocks for which we have logged a 'No LTP' warning
        const loggedLtpWarnings = new Set(); 
        // --- END NEW CODE BLOCK ---

        // --- Processing Logic ---
        for (const order of orderStocks) {
            // 🟢 CRUCIAL: Destructure 'id', 'strikeprice', 'optiontype', and map 'USER' to 'user'
            const { id, stockname, strikeprice, optiontype, limitprice, limitprice_original, type, USER: user, [originalPriceColumnName]: originalprice } = order;
            let performUpdate = false;
            let newLimitPriceToUpdate;
            let newIsMarketToUpdate = null;
            let newIsValidStatus = order.isvalid; 

            // Construct exact Redis Key for Option Premium (e.g., ABCAPITAL_385.0_PE)
            let redisKey = stockname;
            if (strikeprice && optiontype) {
                // Ensure strikeprice matches Python's float() string conversion exactly (e.g. 100 -> '100.0', 385.5 -> '385.5', 385.25 -> '385.25')
                const f = parseFloat(strikeprice);
                const formattedStrike = (f % 1 === 0) ? f.toFixed(1) : f.toString();
                redisKey = `${stockname.trim().toUpperCase()}_${formattedStrike}_${optiontype.trim().toUpperCase()}`;
            }

            // Price comparison logic
            let customlimitprice;
            if (priceCheckMode === 'WatchMarketAndPlace-TL_Buy') {
                customlimitprice = limitprice_original;
            } else {
                customlimitprice = limitprice;
            }
            
            let ltpData = await getLTP(redisKey);
            
            // Check for missing data or missing timestamp
            if (!ltpData || !ltpData.timestamp) {
                
                // --- START MODIFIED LOGIC BLOCK ---
                // Only log the warning if we haven't seen this option key fail before
                if (!loggedLtpWarnings.has(redisKey)) {
                    console.log(`⚠️ WARNING: No valid LTP data found for ${redisKey}. Using DUMMY price of 100.0 for simulation.`);
                    loggedLtpWarnings.add(redisKey);
                }
                
                // INJECT DUMMY DATA FOR SIMULATION
                ltpData = {
                    ltp: "100.0",
                    source: "SIMULATION",
                    timestamp: new Date().toISOString()
                };
                // --- END MODIFIED LOGIC BLOCK ---
            }
            
            // 🟢 MODIFICATION 1: Get ltpSource and ltpTimestamp from ltpData
            const ltpSource = ltpData.source;
            let tsString = ltpData.timestamp; // <--- Extracted the timestamp string
            
            // Fix IST to UTC parsing mismatch for simulation data
            if (!tsString.endsWith('Z') && !tsString.includes('+')) {
                tsString = tsString.replace(' ', 'T') + '+05:30';
            }
            
            const ltpTimestamp = tsString;
            const ltpTime = parseISO(tsString);
            
            // Reject stale ticks. With IST timezone fix, this now works correctly.
            if (!isValid(ltpTime) || Math.abs(differenceInMinutes(new Date(), ltpTime)) > MAX_LTP_AGE_MINUTES) {
                continue;
            }

            const currentLTPForLogic = parseFloat(ltpData.ltp);

            if (priceCheckMode === 'withoutpricecheck' || priceCheckMode === 'withoutpricecheck_originallimit') {
                newLimitPriceToUpdate = (limitprice_original && parseFloat(limitprice_original) > 0) ? parseFloat(limitprice_original) : currentLTPForLogic;
                newIsValidStatus = 'TRUE';
                performUpdate = true;
            } 
            // Logic for WatchMarketAndPlace-Options_Pair
            else if (priceCheckMode === 'WatchMarketAndPlace-Options_Pair') {
                if (type === 'BUY') {
                    // First leg
                    if (String(order.isvalid) === '2' || String(order.isvalid) === '1.5') {
                        continue; // Already executed or pending in Kotak, skip so we don't lose queue priority
                    }
                    if (currentLTPForLogic <= limitprice) {
                        newIsValidStatus = '1';
                        newIsMarketToUpdate = 'TRUE'; // Reverted back to Market Order execution
                    } else {
                        newIsValidStatus = '0';
                    }
                }
                else if (type === 'SELL') {
                    // Second leg - wait for BUY to be complete (isvalid>=3)
                    if (String(order.isvalid) === '2' || String(order.isvalid) === '1.5') {
                        continue; // Already executed or pending in Kotak, skip so we don't lose queue priority
                    }
                    const buyLegForUser = orderStocks.find(o => o.stockname === stockname && o.USER === user && o.type === 'BUY');
                    const isBuyComplete = buyLegForUser && (parseFloat(buyLegForUser.isvalid) >= 3);
                    
                    if (!isBuyComplete) {
                        newIsValidStatus = '0'; 
                    } else {
                        // BUY is done, activate SELL leg targeting profit
                        if (currentLTPForLogic >= limitprice) {
                            newIsValidStatus = '1';
                            newIsMarketToUpdate = 'TRUE'; // Reverted back to Market Order execution
                        } else {
                            newIsValidStatus = '0';
                        }
                    }
                }
                
                if (newIsValidStatus !== String(order.isvalid) || !isNaN(newLimitPriceToUpdate) || newIsMarketToUpdate) {
                    performUpdate = true;
                }
            } 
            // Logic for Exit-Options_Pair (Aggressive Morning Sweep)
            else if (priceCheckMode === 'Exit-Options_Pair') {
                if (type === 'BUY') {
                    // First leg
                    if (['2', '3', '4'].includes(String(order.isvalid))) {
                        continue; // Already executed, skip
                    }
                    // Execute based on CLI arg
                    newIsValidStatus = '1';
                    newIsMarketToUpdate = (orderTypeArg === 'market') ? 'TRUE' : 'FALSE';
                    if (orderTypeArg === 'limit') {
                        // Place limit order exactly at LTP
                        newLimitPriceToUpdate = Math.round((currentLTPForLogic + 0.05) * 100) / 100; // Aggressive tick: +0.05 for BUY
                    }
                }
                else if (type === 'SELL') {
                    // Second leg - still strictly waits for BUY to be complete
                    if (['2', '3', '4'].includes(String(order.isvalid))) {
                        continue; // Already executed, skip
                    }
                    const buyLegForUser = orderStocks.find(o => o.stockname === stockname && o.USER === user && o.type === 'BUY');
                    const isBuyComplete = buyLegForUser && (parseFloat(buyLegForUser.isvalid) >= 3);
                    
                    if (!isBuyComplete) {
                        newIsValidStatus = '0'; 
                    } else {
                        // BUY is done, forcefully snap SELL leg to execute
                        newIsValidStatus = '1';
                        newIsMarketToUpdate = (orderTypeArg === 'market') ? 'TRUE' : 'FALSE';
                        if (orderTypeArg === 'limit') {
                            // Place limit order exactly at LTP
                            newLimitPriceToUpdate = Math.round((currentLTPForLogic - 0.05) * 100) / 100; // Aggressive tick: -0.05 for SELL
                        }
                    }
                }
                
                if (newIsValidStatus !== String(order.isvalid) || !isNaN(newLimitPriceToUpdate) || newIsMarketToUpdate) {
                    performUpdate = true;
                }
            } 
            // Logic for Entry-Options_Pair (Afternoon Sequential Entry)
            else if (priceCheckMode === 'Entry-Options_Pair') {
                if (type === 'BUY') {
                    // First leg - Buy OTM hedge first for margin benefit
                    if (['2', '3', '4'].includes(String(order.isvalid))) {
                        continue; // Already executed, skip
                    }
                    if (currentLTPForLogic < 1.00) {
                        console.log(`[REJECT] ${stockname} BUY Premium ${currentLTPForLogic} is < 1.00. Skipping!`);
                        continue;
                    }
                    // Entry execution based on CLI arg
                    newIsValidStatus = '1';
                    newIsMarketToUpdate = (orderTypeArg === 'market') ? 'TRUE' : 'FALSE';
                    if (orderTypeArg === 'limit') {
                        // Place limit order exactly at LTP
                        newLimitPriceToUpdate = currentLTPForLogic;
                    }
                }
                else if (type === 'SELL') {
                    // Second leg - strictly wait for BUY to be complete (margin benefit active)
                    if (['2', '3', '4'].includes(String(order.isvalid))) {
                        continue; // Already executed, skip
                    }
                    if (currentLTPForLogic < 1.00) {
                        console.log(`[REJECT] ${stockname} SELL Premium ${currentLTPForLogic} is < 1.00. Skipping!`);
                        continue;
                    }
                    const buyLegForUser = orderStocks.find(o => o.stockname === stockname && o.USER === user && o.type === 'BUY');
                    const isBuyComplete = buyLegForUser && (parseFloat(buyLegForUser.isvalid) >= 3);
                    
                    if (!isBuyComplete) {
                        newIsValidStatus = '0'; 
                    } else {
                        // BUY is fully settled, safe to fire SELL leg
                        newIsValidStatus = '1';
                        newIsMarketToUpdate = (orderTypeArg === 'market') ? 'TRUE' : 'FALSE';
                        if (orderTypeArg === 'limit') {
                            // Place limit order exactly at LTP
                            newLimitPriceToUpdate = currentLTPForLogic;
                        }
                    }
                }
                
                if (newIsValidStatus !== String(order.isvalid) || !isNaN(newLimitPriceToUpdate) || newIsMarketToUpdate) {
                    performUpdate = true;
                }
            } 
            
            // 🚨 Database Update Logic
            if (performUpdate) {
                let updateQuery;
                let updateValues;
                let updateMessage;
                
                if (priceCheckMode === 'WatchMarketAndPlace-Options_Pair' || priceCheckMode === 'withoutpricecheck-Options_Pair' || priceCheckMode === 'Exit-Options_Pair' || priceCheckMode === 'Entry-Options_Pair') {
                    let updateFields = ['isvalid = ?'];
                    let updateValuesList = [newIsValidStatus];

                    if (!isNaN(newLimitPriceToUpdate)) {
                        updateFields.push('limitprice = ?');
                        updateValuesList.push(newLimitPriceToUpdate);
                    } 
                    if (newIsMarketToUpdate) {
                        updateFields.push('ismarket = ?');
                        updateValuesList.push(newIsMarketToUpdate);
                    } 
                    
                    if (newIsValidStatus === '1') {
                        successfulOrders.push({
                            User: user,
                            Stock: stockname,
                            OriginalLimit: limitprice,
                            NewLimit: newLimitPriceToUpdate || limitprice,
                            LTP_Time: ltpTimestamp,
                            LTP_Source: ltpSource,
                            Type: type,
                            Mode: priceCheckMode
                        });
                    }

                    updateQuery = `UPDATE ${tableName} SET ${updateFields.join(', ')} WHERE id = ?`;
                    updateValues = [...updateValuesList, id];
                }
                else if (priceCheckMode === 'withoutpricecheck' || priceCheckMode === 'AMO_nocheck') {
                    // withoutpricecheck (updates both) and AMO_nocheck (updates limitprice only)
                    
                    let updateFields = ['limitprice = ?'];
                    let updateValuesList = [newLimitPriceToUpdate];
                    
                    // Only for withoutpricecheck, we need the isvalid update
                    if (priceCheckMode === 'withoutpricecheck') {
                         updateFields.push('isvalid = ?');
                         updateValuesList.push(newIsValidStatus);

                         // 🟢 COLLECTION POINT 3: Collect successful WITHOUTPRICECHECK data (ADDED LTP_Time)
                         successfulOrders.push({
                            User: user,
                            Stock: stockname,
                            OriginalLimit: limitprice,
                            NewLimit: newLimitPriceToUpdate,
                            LTP_Time: ltpTimestamp,  // <--- ADDED
                            LTP_Source: ltpSource,
                            Type: type,
                            Mode: priceCheckMode
                        });
                    } 
                    
                    updateQuery = `UPDATE ${tableName} SET ${updateFields.join(', ')} WHERE stockname = ? AND simulationtime = ? AND is_future = ? `;
                    updateValues = [...updateValuesList, stockname, today, isFutureValue];

                    if (priceCheckMode === 'withoutpricecheck' || priceCheckMode === 'AMO_nocheck') {
                       updateQuery += ` AND type = ?`;
                       updateValues.push(type);
                    }
                }

                if (updateQuery) {
                    await executeQueryInSQL(updateQuery, updateValues);
                }
            } 
        }

    } catch (error) {
        console.error("An error occurred during orchestration:", error);
    } finally {
        // 🟢 NEW: Display generalized summary table for all modes
        if (successfulOrders.length > 0) {
            console.log("\n=========================================================================");
            console.log(`   ✅ ORCHESTRATOR SUMMARY: Successful Orders for Mode: ${priceCheckMode}`);
            console.log("=========================================================================");
            console.table(successfulOrders);
            console.log("=========================================================================");

            // --- Send Telegram Alert when Price Condition is Met ---
            try {
                const https = require('https');
                let botToken = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE";
                let chatId = "-1002365534285"; // Status and Warnings group
                
                let isBuy = priceCheckMode.includes('Buy');
                let modeTitle = isBuy ? "BUY ORDER CONDITION MET (LTP ≤ Base Price)" : "SQUARE-OFF SELL CONDITION MET (LTP ≥ Target Price)";
                
                let msg = `🎯 <b>${modeTitle}</b>\n`;
                msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n";
                successfulOrders.forEach((o, i) => {
                    let origPrice = o.OriginalLimit ? `₹${parseFloat(o.OriginalLimit).toFixed(2)}` : 'N/A';
                    let newLtp = o.NewLimit ? `₹${parseFloat(o.NewLimit).toFixed(2)}` : 'N/A';
                    msg += `<b>${i + 1}. ${o.Stock}</b> (${o.Type || (isBuy ? 'BUY' : 'SELL')}) - ${o.User}\n`;
                    msg += `  • Trigger LTP: ${newLtp}\n`;
                    msg += `  • Target/Base Price: ${origPrice}\n`;
                    msg += `  • Status: Order Validated ➔ Sent for Execution\n`;
                    msg += "------------------------------------\n";
                });

                const data = JSON.stringify({ chat_id: chatId, text: msg, parse_mode: 'HTML' });
                const options = {
                    hostname: 'api.telegram.org',
                    port: 443,
                    path: `/bot${botToken}/sendMessage`,
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
                };
                await new Promise((resolve) => {
                    const req = https.request(options, (res) => {
                        res.on('data', () => {});
                        res.on('end', () => {
                            console.log("Sent Telegram Price Condition Met Alert.");
                            resolve();
                        });
                    });
                    req.on('error', (e) => {
                        console.error("Telegram alert error:", e);
                        resolve();
                    });
                    req.write(data);
                    req.end();
                });
            } catch (e_alert) {
                console.error("Error dispatching Telegram alert:", e_alert);
            }

        } else {
             console.log(`\n✅ ORCHESTRATOR SUMMARY: No orders met the conditions for update in mode: ${priceCheckMode}.`);
        }
        
        console.log("Orchestration finished. Connections closed.");
        // Close the MySQL connection pool and exit the process
        closeRedisConnection();
        pool.end(() => {
            console.log("MySQL pool closed. Exiting process.");
            process.exit();
        });
    }
})();

// Use the connection pool to execute queries
function executeQueryInSQL(sql, values) {
    return new Promise((resolve, reject) => {
        pool.query(sql, values, (err, data) => {
            if (err) return reject(err);
            resolve(data);
        });
    });
}