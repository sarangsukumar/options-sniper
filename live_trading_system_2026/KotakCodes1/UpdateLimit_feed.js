const mysql = require('mysql');
const moment = require('moment');
const { parseISO, differenceInMinutes, isValid } = require('date-fns');

// Import the new Redis handler and connection closer
const { getLTP, closeRedisConnection } = require('./readhandler');

const today = moment().format('YYYY-MM-DD');

// --- Configuration ---
const MAX_LTP_AGE_MINUTES = 2;

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
    const isFutureValue = process.argv[2];
    
function getTickSize(price) {
    if (price <= 250) return 0.01;
    if (price <= 1000) return 0.05;
    if (price <= 2500) return 0.10;
    if (price <= 5000) return 0.25;
    if (price <= 10000) return 0.50;
    if (price <= 20000) return 1.00;
    return 5.00;
}

const priceCheckMode = process.argv[3];
    
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
    const tableName = isAmoMode ? 'orders_AMO' : 'orders';
    const originalPriceColumnName = isAmoMode ? 'buy_price' : 'price';

    try {
        let orderStocks;
        
        // 🚨 Order Selection Logic: Reading orders based on priceCheckMode
        if (priceCheckMode === 'WatchMarketAndPlace-TL_Buy') {
            console.log(`Special mode: ${priceCheckMode}. Reading all BUY orders regardless of 'isvalid' status.`);
            orderStocks = await executeQueryInSQL(
                `SELECT * FROM ${tableName} WHERE simulationtime = ? AND is_future = ? AND type = 'BUY'`,
                [today, isFutureValue]
            );
        }
        else if (priceCheckMode.includes('WatchMarketAndPlace-TL_Sell')) {
            console.log(`Special mode: ${priceCheckMode}. Reading all SELL orders regardless of 'isvalid' status.`);
            orderStocks = await executeQueryInSQL(
                `SELECT * FROM ${tableName} WHERE simulationtime = ? AND is_future = ? AND type = 'SELL'`,
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
            // 🟢 CRUCIAL: Destructure 'id' and map 'USER' to 'user'
            const { id, stockname, limitprice, limitprice_original, type, USER: user, [originalPriceColumnName]: originalprice } = order;
            let performUpdate = false;
            let newLimitPriceToUpdate;
            let newIsValidStatus = order.isvalid; 

            // Price comparison logic
            let customlimitprice;
            if (priceCheckMode === 'WatchMarketAndPlace-TL_Buy') {
                customlimitprice = limitprice_original;
            } else {
                customlimitprice = limitprice;
            }
            
            const ltpData = await getLTP(stockname);
            
            // Check for missing data or missing timestamp
            if (!ltpData || !ltpData.timestamp) {
                
                // --- START MODIFIED LOGIC BLOCK ---
                // Only log the warning if we haven't seen this stock fail before
                if (!loggedLtpWarnings.has(stockname)) {
                    console.log(`⚠️ WARNING: No valid LTP data (or timestamp) found for stock: ${stockname}. Subsequent orders for this stock will be skipped without further warnings.`);
                    loggedLtpWarnings.add(stockname);
                }
                // --- END MODIFIED LOGIC BLOCK ---

                continue; // This skips the rest of the loop for the current order
            }
            
            // 🟢 MODIFICATION 1: Get ltpSource and ltpTimestamp from ltpData
            const ltpSource = ltpData.source;
            const ltpTimestamp = ltpData.timestamp; // <--- Extracted the timestamp string
            const ltpTime = parseISO(ltpData.timestamp);
            
            if (!isValid(ltpTime) || differenceInMinutes(new Date(), ltpTime) > MAX_LTP_AGE_MINUTES) {
                continue;
            }

            const currentLTPForLogic = parseFloat(ltpData.ltp);

            if (priceCheckMode === 'withoutpricecheck' || priceCheckMode === 'withoutpricecheck_originallimit') {
                newLimitPriceToUpdate = (limitprice_original && parseFloat(limitprice_original) > 0) ? parseFloat(limitprice_original) : currentLTPForLogic;
                newIsValidStatus = 'TRUE';
                performUpdate = true;
            } 
            // Logic for WatchMarketAndPlace-TL_Buy (User Deduplication)
            else if (priceCheckMode === 'WatchMarketAndPlace-TL_Buy') {
                
                const userStockKey = `${stockname}:${user}`;

                // Condition: Price met AND not executed for this user/stock combination
                if (currentLTPForLogic <= customlimitprice && !executedUserStocks.has(userStockKey)) {
                    
                    newIsValidStatus = 'TRUE';
                    newLimitPriceToUpdate = currentLTPForLogic; 
                    
                    executedUserStocks.add(userStockKey);
                    
                } else {
                    // Condition: Not met OR already executed by this user -> set to FALSE
                    newIsValidStatus = 'FALSE';
                }
                
                if (newIsValidStatus !== order.isvalid || !isNaN(newLimitPriceToUpdate)) {
                    performUpdate = true;
                }
            } 
            // Logic for WatchMarketAndPlace-TL_Sell
            else if (priceCheckMode.includes('WatchMarketAndPlace-TL_Sell')) {
                if (currentLTPForLogic >= customlimitprice) {
                    newIsValidStatus = 'TRUE';
                    let tickSize = getTickSize(currentLTPForLogic);
                    newLimitPriceToUpdate = Math.round((currentLTPForLogic - tickSize) * 100) / 100; 
                } else {
                    newIsValidStatus = 'FALSE';
                }
                
                if (newIsValidStatus !== order.isvalid || !isNaN(newLimitPriceToUpdate)) {
                    performUpdate = true;
                }
            }
            // Logic for TL_sell_withpricecheck_greaterthan
            else if (priceCheckMode === 'TL_sell_withpricecheck_greaterthan') {
                if (currentLTPForLogic >= customlimitprice) {
                    newLimitPriceToUpdate = currentLTPForLogic;
                } 
                
                newIsValidStatus = 'TRUE'; 
                performUpdate = true;
            } 
            
            // 🚨 Database Update Logic
            if (performUpdate) {
                let updateQuery;
                let updateValues;
                let updateMessage;
                
                if (priceCheckMode === 'WatchMarketAndPlace-TL_Buy') {
                    let updateFields = ['isvalid = ?'];
                    let updateValuesList = [newIsValidStatus];

                    if (!isNaN(newLimitPriceToUpdate)) {
                        updateFields.push('limitprice = ?');
                        updateValuesList.push(newLimitPriceToUpdate);
                    } 
                    
                    // 🟢 COLLECTION POINT 1: Collect successful BUY order data (ADDED LTP_Time)
                    if (newIsValidStatus === 'TRUE') {
                        successfulOrders.push({
                            User: user,
                            Stock: stockname,
                            OriginalLimit: limitprice_original,
                            NewLimit: newLimitPriceToUpdate,
                            LTP_Time: ltpTimestamp,  // <--- ADDED
                            LTP_Source: ltpSource,
                            Type: type,
                            Mode: priceCheckMode
                        });
                    }

                    updateQuery = `UPDATE ${tableName} SET ${updateFields.join(', ')} WHERE id = ? AND stockname = ? AND simulationtime = ? AND is_future = ? AND type = 'BUY'`;
                    updateValues = [...updateValuesList, id, stockname, today, isFutureValue];
                } 
                else if (priceCheckMode.includes('WatchMarketAndPlace-TL_Sell') || priceCheckMode === 'TL_sell_withpricecheck_greaterthan') {
                    // TL_Sell and TL_sell_withpricecheck_greaterthan
                    let updateFields = ['isvalid = ?'];
                    let updateValuesList = [newIsValidStatus];
                    
                    if (!isNaN(newLimitPriceToUpdate)) {
                        updateFields.push('limitprice = ?');
                        updateValuesList.push(newLimitPriceToUpdate);
                    }
                    
                    // 🟢 COLLECTION POINT 2: Collect successful SELL order data (ADDED LTP_Time)
                    if (newIsValidStatus === 'TRUE') {
                        successfulOrders.push({
                            User: user,
                            Stock: stockname,
                            OriginalLimit: limitprice,
                            NewLimit: newLimitPriceToUpdate || limitprice,
                            LTP_Time: ltpTimestamp,  // <--- ADDED
                            LTP_Source: ltpSource,
                            Type: type,
                            Mode: priceCheckMode
                        });
                    }
                    
                    updateQuery = `UPDATE ${tableName} SET ${updateFields.join(', ')} WHERE stockname = ? AND simulationtime = ? AND is_future = ? AND type = 'SELL'`;
                    updateValues = [...updateValuesList, stockname, today, isFutureValue];
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