/**
 * fill_missing_f1_data.js
 * =======================
 * Dedicated high-speed bulk loader script to backfill missing F1 futures tick data into 
 * markets.scrapdata_F1 across custom date ranges.
 *
 * Usage:
 *  node pipeline/fill_missing_f1_data.js 2026-07-20 2026-07-28
 */

var BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const csv = require('csv-parser');
const mysql = require('mysql');
const { exec } = require('child_process');
const path = require('path');

const parentDir = path.dirname(__dirname);

// Account Configurations
const ACCOUNT_CONFIGS = {
    Amrit: {
        name: "Amrit",
        appKey: "77059JQ7633PoSc1mk465580B6wp1x04",
        appSecret: "6P9^377d3*412585q(527i3ZgJ437040",
        sessionFile: path.join(parentDir, 'auth', 'icicisession.txt'),
        otpScript: path.join(parentDir, 'auth', '2.OTP_Amrit.py')
    },
    Manisha: {
        name: "Manisha",
        appKey: "1f3Pi887R1652C91_76J6808z8191jq~",
        appSecret: "4d7(89!0_3~8+11%49J38+g340k99n2~",
        sessionFile: path.join(parentDir, 'auth', 'icicisession_Manisha.txt'),
        otpScript: path.join(parentDir, 'auth', '2.OTP_Manisha.py')
    }
};

let activeAccountName = "Amrit"; // Direct to active Amrit token
let activeConfig = ACCOUNT_CONFIGS[activeAccountName];

const MASTER_FILE = path.join(parentDir, 'config', 'ICICImaster.csv');
const TABLENAME = "scrapdata_F1";
const isfuture = 'F1';
const source = "ICICI";

const dbConfig = {
    host: 'localhost',
    user: 'root',
    password: 'root',
    database: 'markets'
};

const connection = mysql.createConnection(dbConfig);
let breeze = new BreezeConnect({ appKey: activeConfig.appKey });

const fromDateArg = process.argv[2] || "2026-07-20";
const toDateArg   = process.argv[3] || "2026-07-28";

function getDatesInRange(startDate, endDate) {
    const dates = [];
    const currentDate = new Date(startDate);
    const lastDate = new Date(endDate);

    while (currentDate <= lastDate) {
        const dayOfWeek = currentDate.getDay();
        if (dayOfWeek !== 0 && dayOfWeek !== 6) { 
            const dateString = currentDate.toISOString().slice(0, 10);
            dates.push(dateString);
        }
        currentDate.setDate(currentDate.getDate() + 1);
    }
    return dates;
}

const expiryDatesList = [
    "27 Jan 2011","24 Feb 2011","31 Mar 2011","28 Apr 2011","26 May 2011","30 Jun 2011","28 Jul 2011","25 Aug 2011","29 Sep 2011","25 Oct 2011","24 Nov 2011","29 Dec 2011",
    "25 Jan 2012","23 Feb 2012","29 Mar 2012","26 Apr 2012","31 May 2012","28 Jun 2012","26 Jul 2012","30 Aug 2012","27 Sep 2012","25 Oct 2012","29 Nov 2012","27 Dec 2012",
    "31 Jan 2013","28 Feb 2013","28 Mar 2013","25 Apr 2013","30 May 2013","27 Jun 2013","25 jul 2013","29 Aug 2013","26 Sep 2013","31 Oct 2013","28 Nov 2013","26 Dec 2013",
    "30 Jan 2014","26 Feb 2014","27 Mar 2014","24 Apr 2014","29 May 2014","26 Jun 2014","31 Jul 2014","28 Aug 2014","25 Sep 2014","30 Oct 2014","27 Nov 2014","24 Dec 2014",
    "29 Jan 2015","26 Feb 2015","26 Mar 2015","30 Apr 2015","28 May 2015","25 Jun 2015","30 Jul 2015","27 Aug 2015","24 Sep 2015","29 Oct 2015","26 Nov 2015","31 Dec 2015",
    "28 Jan 2016","25 Feb 2016","31 Mar 2016","28 Apr 2016","26 May 2016","30 Jun 2016","28 Jul 2016","25 Aug 2016","29 Sep 2016","27 Oct 2016","24 Nov 2016","29 Dec 2016",
    "25 Jan 2017","23 Feb 2017","30 Mar 2017","27 Apr 2017","25 May 2017","29 Jun 2017","27 Jul 2017","31 Aug 2017","28 Sep 2017","26 Oct 2017","30 Nov 2017","28 Dec 2017",
    "25 Jan 2018","22 Feb 2018","28 Mar 2018","26 Apr 2018","31 May 2018","28 Jun 2018","26 Jul 2018","30 Aug 2018","27 Sep 2018","25 Oct 2018","29 Nov 2018","27 Dec 2018",
    "31 Jan 2019","28 Feb 2019","28 Mar 2019","25 Apr 2019","30 May 2019","27 Jun 2019","25 Jul 2019","29 Aug 2019","26 Sep 2019","24 Oct 2019","28 Nov 2019","26 Dec 2019",
    "30 Jan 2020","27 Feb 2020","26 Mar 2020","30 Apr 2020","28 May 2020","25 Jun 2020","30 Jul 2020","27 Aug 2020","24 Sep 2020","29 Oct 2020","26 Nov 2020","31 Dec 2020",
    "28 Jan 2021","25 Feb 2021","25 Mar 2021","29 Apr 2021","27 May 2021","24 Jun 2021","29 Jul 2021","26 Aug 2021","30 Sep 2021","28 Oct 2021","25 Nov 2021","30 Dec 2021",
    "27 Jan 2022","24 Feb 2022","31 Mar 2022","28 Apr 2022","26 May 2022","30 Jun 2022","28 Jul 2022","25 Aug 2022","29 Sep 2022","27 Oct 2022","24 Nov 2022","29 Dec 2022",
    "25 Jan 2023","23 Feb 2023","29 Mar 2023","27 Apr 2023","25 May 2023","28 Jun 2023","27 Jul 2023","31 Aug 2023","28 Sep 2023","26 Oct 2023","30 Nov 2023","28 Dec 2023",
    "25 Jan 2024","29 Feb 2024","28 Mar 2024","25 Apr 2024","30 May 2024","27 Jun 2024","25 Jul 2024","29 Aug 2024","26 Sep 2024","31 Oct 2024","28 Nov 2024","26 Dec 2024",
    "30 Jan 2025","27 Feb 2025","27 Mar 2025","24 Apr 2025","29 May 2025","26 Jun 2025","31 Jul 2025","28 Aug 2025","30 Sep 2025","28 Oct 2025","25 Nov 2025","30 Dec 2025",
    "27 Jan 2026","24 Feb 2026","31 Mar 2026","28 Apr 2026","26 May 2026","30 Jun 2026","28 Jul 2026","25 Aug 2026","29 Sep 2026","27 Oct 2026","24 Nov 2026","29 Dec 2026"
];

function resetTime(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    return d;
}

function getExpiryDate(expiryDatesList, today) {
    const todayReset = resetTime(today);
    const expiryDates = expiryDatesList.map(dateStr => resetTime(new Date(dateStr)));
    const validExpiries = expiryDates.filter(expDate => todayReset <= expDate);

    if (validExpiries.length >= 1) {
        return validExpiries[0].addHours(23).toISOString().slice(0, 10);
    } else {
        return expiryDates[expiryDates.length - 1].addHours(23).toISOString().slice(0, 10);
    }
}

Date.prototype.addHours = function (h) {
    this.setTime(this.getTime() + (h * 60 * 60 * 1000));
    return this;
};

function withTimeout(promise, ms, errorMessage = "Timeout exceeded") {
    let timeoutId;
    const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(errorMessage)), ms);
    });
    return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timeoutId));
}

function readTextFileSync(filePath) {
    try {
        return fs.readFileSync(filePath, 'utf8').trim();
    } catch (err) {
        return null;
    }
}

async function authenticateOrRenew() {
    try {
        console.log(`[Auth] Logging in for ${activeAccountName}...`);
        const session_key = readTextFileSync(activeConfig.sessionFile);
        await withTimeout(breeze.generateSession(activeConfig.appSecret, session_key), 15000);
        console.log(`[Auth] Authenticated ${activeAccountName} account successfully.`);
    } catch (err) {
        console.error(`[Auth Error]:`, err.message || err);
        process.exit(1);
    }
}

function fetchBreezeData(stockCode, expiryDate, fromDateIso, toDateIso) {
    return breeze.getHistoricalDatav2({
        interval: "1minute",
        fromDate: fromDateIso,
        toDate: toDateIso,
        stockCode: stockCode,
        exchangeCode: "NFO",
        productType: "futures",
        expiryDate: expiryDate,
        right: "others",
        strikePrice: "0"
    });
}

function readMasterStockCodes() {
    const stocks = [];
    return new Promise((resolve, reject) => {
        fs.createReadStream(MASTER_FILE)
            .pipe(csv())
            .on('data', row => {
                const scrip = row.scripcode ? row.scripcode.trim() : '';
                const display = row.stockCodes ? row.stockCodes.trim() : scrip;
                if (scrip && !stocks.some(s => s.scrip === scrip)) {
                    stocks.push({ scrip: scrip, display: display });
                }
            })
            .on('end', () => resolve(stocks))
            .on('error', reject);
    });
}

async function runBulkBackfill() {
    const datesToFill = getDatesInRange(fromDateArg, toDateArg);
    console.log(`=======================================================`);
    console.log(`F1 FUTURES BULK BACKFILL UTILITY`);
    console.log(`=======================================================`);
    console.log(`Target Range : ${fromDateArg} to ${toDateArg}`);
    console.log(`Dates Count  : ${datesToFill.length} trading days`);
    console.log(`Target DB    : markets.${TABLENAME}`);
    console.log(`=======================================================\n`);

    const stocks = await readMasterStockCodes();
    console.log(`[Master CSV] Loaded ${stocks.length} active futures stocks.`);

    for (let d = 0; d < datesToFill.length; d++) {
        const targetDate = datesToFill[d];
        const expiryDateIso = getExpiryDate(expiryDatesList, new Date(targetDate));
        const expiryDateFormatted = `${expiryDateIso}T07:00:00.000Z`;

        const fromDateIso = `${targetDate}T00:00:00.000Z`;
        const toDateIso   = `${targetDate}T23:59:59.000Z`;

        console.log(`\n-------------------------------------------------------`);
        console.log(`📅 [Day ${d + 1}/${datesToFill.length}] Fetching F1 Futures for ${targetDate} (Expiry: ${expiryDateIso})`);
        console.log(`-------------------------------------------------------`);

        let daySuccess = 0;

        for (let s = 0; s < stocks.length; s++) {
            const stockObj = stocks[s];

            try {
                const breezeResponse = await withTimeout(
                    fetchBreezeData(stockObj.scrip, expiryDateFormatted, fromDateIso, toDateIso),
                    10000,
                    `Timeout for ${stockObj.scrip}`
                );

                const responseData = breezeResponse.Success || breezeResponse.success || [];

                if (Array.isArray(responseData) && responseData.length > 0) {
                    const insertValues = responseData.map(item => {
                        const rawDate = item.datetime || item.datetime_val || '';
                        const formattedTime = rawDate ? rawDate.replace('T', ' ').replace('.000Z', '') : targetDate;

                        return [
                            stockObj.display,
                            formattedTime,
                            parseFloat(item.open || 0),
                            parseFloat(item.high || 0),
                            parseFloat(item.low || 0),
                            parseFloat(item.close || 0),
                            parseInt(item.volume || 0, 10),
                            parseInt(item.open_interest || item.open_interest_val || 0, 10),
                            source,
                            isfuture,
                            targetDate
                        ];
                    });

                    const sql = `
                        INSERT INTO ${TABLENAME} 
                        (stockname, time, open, high, low, close, volume, open_interest, source, is_future, date) 
                        VALUES ? 
                        ON DUPLICATE KEY UPDATE 
                            open = VALUES(open), 
                            high = VALUES(high), 
                            low = VALUES(low), 
                            close = VALUES(close), 
                            volume = VALUES(volume), 
                            open_interest = VALUES(open_interest);
                    `;

                    await new Promise((resQuery, rejQuery) => {
                        connection.query(sql, [insertValues], (errQuery, result) => {
                            if (errQuery) rejQuery(errQuery);
                            else resQuery(result);
                        });
                    });
                    daySuccess++;
                    process.stdout.write(`\r[Progress] Processing stock ${s + 1}/${stocks.length}: ${stockObj.display} (${responseData.length} bars inserted)`);
                }
            } catch (err) {
                // Silently skip if no data/timeout
            }
        }
        console.log(`\n✔ Completed ${targetDate}: Successfully inserted data for ${daySuccess}/${stocks.length} stocks.`);
    }
}

async function main() {
    try {
        await authenticateOrRenew();
        await runBulkBackfill();
        console.log(`\n[Backfill Complete] All missing F1 futures dates inserted successfully.`);
    } catch (err) {
        console.error(`[Fatal Backfill Error]:`, err);
    } finally {
        connection.end();
    }
}

main();
