
   
/*App Name5P55570610
App Source7183
User IDBHaRF0TdQns
PasswordSJ1kIiC4ZaH
User Key70a2pFeYS3J1eChtEMigrTrgrNTindZX
Encryption KeyQMgpN1WoUsP4WuUrkl4gjYn6kvK7pVuC
Valid up to1/1/2099 12:00:00 PM
DF14K6P2
--sarang below
App Name
5P54556159
App Source
7158
User ID
k3VyvRYUMqa
Password
NFh3pNiUBRx
User Key
3yuBWUZr0ZOYcp5b1ILYyzsz3S0GyBAA
Encryption Key
8a7y0a1AXbXb87TAeyJvneWKHY7ehK34
Valid up to
1/1/2099 12:00:00 PM
*/
// Configuration for your app
const { spawn } = require('child_process');
const fs = require('fs');
   
// Calling the readFileSync() method
// to read 'input.txt' file

/*
let csvfile=`EICHERMOT,910
ACC,22
ADANIPORTS,15083
AXISBANK,5900
`;*/
const csvfile = fs.readFileSync('./scripmaster-csv-format.csv',
            {encoding:'utf8', flag:'r'});

var moment = require('moment');
var mysql = require('mysql');
let mysqlConfig = {
    host: 'localhost',
    user: 'root',
    password: 'root',
    database: 'markets'
};

let existingRows=new Set();

let  conf = {
     "appSource": "7183",
    "appName": "5P55570610",
    "userId": "BHaRF0TdQns",
    "password": "SJ1kIiC4ZaH",
    "userKey": "70a2pFeYS3J1eChtEMigrTrgrNTindZX",
    "encryptionKey": "QMgpN1WoUsP4WuUrkl4gjYn6kvK7pVuC"
}

const { FivePaisaClient } = require("5paisajs")
let chunk_size=6000;

let scripCodeMap=new Map();
let dateFrom= "2024-07-16"//new Date().toISOString().substring(0,10);// 

console.log(dateFrom);
let currentHour=new Date().getHours();
let currentMinute=new Date().getMinutes();
//console.log(currentHour);
//console.log(currentMinute);
let timeFrom=process.argv[3] ||'09:15:00';//new Date().toISOString().substring(0,10);//
let timeTo=process.argv[4] ||'14:49:00';//new Date().toISOString().substring(0,10);//



// timeFrom=process.argv[3] ||'09:15:00';
  //      timeTo=process.argv[4] ||'09:43:00';

let dateTo=dateFrom;//new Date().toISOString().substring(0,10);

let scripNameMap=new Map();

csvfile.split("\n").forEach(itm=>{
    if(!itm)
        return;
    let temparr= itm.split(",");
    if(temparr[0]=="N" && temparr[1]=="C" ){
        scripCodeMap.set(temparr[3],temparr[2]);
        scripNameMap.set(temparr[2],temparr[3]);
    }

})   
//let validNames='ACC,ADANIENT,ADANIPORTS,AMBUJACEM,APOLLOTYRE,ASHOKLEY,ASIANPAINT,AUROPHARMA,AXISBANK,BAJAJFINSV,BAJFINANCE,BANDHANBNK,BANKBARODA,BHARATFORG,BHARTIARTL,BHEL,BOSCHLTD,BPCL,BRITANNIA,CANBK,CIPLA,COALINDIA,DLF,DRREDDY,EICHERMOT,ESCORTS,FEDERALBNK,GAIL,GOLDBEES,GRASIM,HCLTECH,HDFC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,ITC,JINDALSTEL,JSWSTEEL,JUBLFOOD,KOTAKBANK,LICHSGFIN,LT,LUPIN,M&M,M&MFIN,MARUTI,MFSL,MUTHOOTFIN,NESTLEIND,NIFTY,NMDC,NTPC,ONGC,PEL,PFC,PNB,POWERGRID,RBLBANK,RECLTD,RELIANCE,SAIL,SBIN,SHREECEM,SIEMENS,SRTRANSFIN,SUNPHARMA,SUNTV,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,ULTRACEMCO,UPL,VEDL,VOLTAS,WIPRO,ZEEL';
            //let validNames='3MINDIA,ABB,POWERINDIA,ACC,AIAENG,APLAPOLLO,AUBANK,AARTIDRUGS,AARTIIND,AAVAS,ABBOTINDIA,ADANIENT,ADANIGREEN,ADANIPORTS,ATGL,ADANITRANS,ABCAPITAL,ABFRL,ADVENZYMES,AEGISCHEM,AFFLE,AJANTPHARM,AKZOINDIA,APLLTD,ALKEM,ALKYLAMINE,AMARAJABAT,AMBER,AMBUJACEM,ANGELBRKG,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASHOKA,ASIANPAINT,ASTERDM,ASTRAZEN,ASTRAL,ATUL,AUROPHARMA,DMART,AXISBANK,BASF,BSE,BAJAJ-AUTO,BAJAJCON,BAJAJELEC,BAJFINANCE,BAJAJFINSV,BAJAJHLDNG,BALKRISIND,BANKBARODA,BATAINDIA,BAYERCROP,BERGEPAINT,BDL,BHARATFORG,BHEL,BHARATRAS,BIOCON,BIRLACORPN,BSOFT,BLISSGVS,BLUEDART,BLUESTARCO,BOSCHLTD,BRITANNIA,BURGERKING,CCL,CESC,,CSBBANK,CADILAHC,CANFINHOME,CAPLIPOINT,CGCL,CASTROLIND,CEATLTD,CDSL,CENTURYPLY,CENTURYTEX,CHALET,CHAMBLFERT,CHOLAFIN,CIPLA,CUB,COALINDIA,COCHINSHIP,COFORGE,COLPAL,CAMS,CONCOR,COROMANDEL,CREDITACC,CUMMINSIND,CYIENT,DCBBANK,DLF,DABUR,DALBHARAT,DEEPAKNTR,DHANI,DBL,DCAL,DIVISLAB,DIXON,LALPATHLAB,DRREDDY,EIDPARRY,EPL,EICHERMOT,ELGIEQUIP,EMAMILTD,ENDURANCE,ENGINERSIN,EQUITAS,ERIS,ESCORTS,EXIDEIND,FEDERALBNK,FINEORG,FINPIPE,FRETAIL,GAIL,GEPIL,GMRINFRA,GALAXYSURF,GRSE,GARFIBRES,GICRE,GILLETTE,GLAND,GLAXO,GLENMARK,GODFRYPHLP,GODREJAGRO,GODREJCP,GODREJIND,GODREJPROP,GRAPHITE,GRASIM,GREAVESCOT,GRINDWELL,GUJALKALI,FLUOROCHEM,GUJGASLTD,GSPL,HEG,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HFCL,HAVELLS,HEIDELBERG,HEROMOTOCO,HSCL,HINDALCO,HAL,HINDUNILVR,HONAUT,HUDCO,HDFC,HUHTAMAKI,ICICIBANK,ICICIGI,ICICIPRULI,IDFCFIRSTB,IFBIND,IIFL,IIFLWAM,IOLCP,IRB,IRCON,ITC,ITI,IBULHSGFIN,INDIAMART,INDIANB,IEX,INDHOTEL,IOC,IRCTC,INDOCO,IGL,INDUSTOWER,INFIBEAM,NAUKRI,INFY,INGERRAND,INOXLEISUR,INTELLECT,INDIGO,IPCALAB,JBCHEPHARM,JKLAKSHMI,JKPAPER,JKTYRE,JMFINANCIL,JSWENERGY,JAMNAAUTO,JINDALSAW,JSLHISAR,JINDALSTEL,JCHAC,JUBLFOOD,JUSTDIAL,KEI,KPITTECH,KRBL,KSB,KAJARIACER,KALPATPOWR,KANSAINER,KARURVYSYA,KEC,KOTAKBANK,L&TFH,LTTS,LAOPALA,LAXMIMACH,LTI,LT,LAURUSLABS,LEMONTREE,LUPIN,MASFIN,MRF,MGL,MAHSCOOTER,M&MFIN,M&M,MAHLOG,MRPL,MARICO,MARUTI,MFSL,MAXHEALTH,MAZDOCK,METROPOLIS,MINDTREE,MINDACORP,MINDAIND,MIDHANI,MOTILALOFS,MCX,NATCOPHARM,NBCC,NCC,NESCO,NHPC,NLCINDIA,NMDC,NTPC,NH,NATIONALUM,NFL,NAVINFLUOR,NESTLEIND,OBEROIRLTY,ONGC,OIL,OFSS,ORIENTELEC,PIIND,PNBHOUSING,PVR,PAGEIND,PERSISTENT,PETRONET,PFIZER,PHILIPCARB,PHOENIXLTD,PIDILITIND,PEL,POLYPLEX,POWERGRID,PRESTIGE,PRINCEPIPE,PRSMJOHNSN,PGHL,PGHH,PNB,RBLBANK,RECLTD,RHIM,RITES,RADICO,RVNL,RAJESHEXPO,RALLIS,RCF,RATNAMANI,RAYMOND,REDINGTON,RELAXO,RELIANCE,RESPONIND,SBICARD,SBILIFE,SIS,SJVN,SKFINDIA,SRF,SANOFI,SCHAEFFLER,SEQUENT,SFL,SCI,SHREECEM,SHRIRAMCIT,SRTRANSFIN,SIEMENS,SOLARINDS,SONATSOFTW,SPICEJET,STARCEMENT,SBIN,SAIL,SWSOLAR,STLTECH,STAR,SUDARSCHEM,SUMICHEM,SPARC,SUNTV,SUNCLAYLTD,SUNDRMFAST,SUNTECK,SUPRAJIT,SUPREMEIND,SUPPETRO,SUVENPHAR,SWANENERGY,SYNGENE,TCNSBRANDS,TTKPRESTIG,TV18BRDCST,TVSMOTOR,TANLA,TASTYBITE,TATACHEM,TATACOFFEE,TATACOMM,TCS,TATACONSUM,TATAELXSI,TATAINVEST,TATAMTRDVR,TATAPOWER,TATASTEEL,TECHM,NIACL,RAMCOCEM,THERMAX,THYROCARE,TITAN,TORNTPHARM,TORNTPOWER,TRENT,UCOBANK,UFLEX,UTIAMC,UJJIVAN,UJJIVANSFB,ULTRACEMCO,UNIONBANK,UBL,MCDOWELL-N,VGUARD,VMART,VIPIND,VSTIND,VAKRANGEE,VARROC,VBL,VOLTAS,WESTLIFE,WHIRLPOOL,WIPRO,ZEEL,ZENSARTECH,ZYDUSWELL,ECLERX';
           // let validNames='3MINDIA,ABB,POWERINDIA,ACC,AIAENG,APLAPOLLO,AUBANK,AARTIDRUGS,AARTIIND,AAVAS,ABBOTINDIA,ADANIENT,ADANIGREEN,ADANIPORTS,ATGL,ADANITRANS,ABCAPITAL,ABFRL,ADVENZYMES,AEGISCHEM,AFFLE,AJANTPHARM,AKZOINDIA,APLLTD,ALKEM,ALKYLAMINE,AMARAJABAT,AMBER,AMBUJACEM,ANGELBRKG,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASHOKA,ASIANPAINT,ASTERDM,ASTRAZEN,ASTRAL,ATUL,AUROPHARMA,DMART,AXISBANK,BASF,BSE,BAJAJ-AUTO,BAJAJCON,BAJAJELEC,BAJFINANCE,BAJAJFINSV,BAJAJHLDNG,BALKRISIND,BANKBARODA,BATAINDIA,BAYERCROP,BERGEPAINT,BDL,BHARATFORG,BHEL,BHARATRAS,BIOCON,BIRLACORPN,BSOFT,BLISSGVS,BLUEDART,BLUESTARCO,BOSCHLTD,BRITANNIA,BURGERKING,CCL,CESC,,CSBBANK,CADILAHC,CANFINHOME,CAPLIPOINT,CGCL,CASTROLIND,CEATLTD,CDSL,CENTURYPLY,CENTURYTEX,CHALET,CHAMBLFERT,CHOLAFIN,CIPLA,CUB,COALINDIA,COCHINSHIP,COFORGE,COLPAL,CAMS,CONCOR,COROMANDEL,CREDITACC,CUMMINSIND,CYIENT,DCBBANK,DLF,DABUR,DALBHARAT,DEEPAKNTR,DHANI,DBL,DCAL,DIVISLAB,DIXON,LALPATHLAB,DRREDDY,EIDPARRY,EPL,EICHERMOT,ELGIEQUIP,EMAMILTD,ENDURANCE,ENGINERSIN,EQUITAS,ERIS,ESCORTS,EXIDEIND,FEDERALBNK,FINEORG,FINPIPE,FRETAIL,GAIL,GEPIL,GMRINFRA,GALAXYSURF,GRSE,GARFIBRES,GICRE,GILLETTE,GLAND,GLAXO,GLENMARK,GODFRYPHLP,GODREJAGRO,GODREJCP,GODREJIND,GODREJPROP,GRAPHITE,GRASIM,GREAVESCOT,GRINDWELL,GUJALKALI,FLUOROCHEM,GUJGASLTD,GSPL,HEG,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HFCL,HAVELLS,HEIDELBERG,HEROMOTOCO,HSCL,HINDALCO,HAL,HINDUNILVR,HONAUT,HUDCO,HDFC,HUHTAMAKI,ICICIBANK,ICICIGI,ICICIPRULI,IDFCFIRSTB,IFBIND,IIFL,IIFLWAM,IOLCP,IRB,IRCON,ITC,ITI,IBULHSGFIN,INDIAMART,INDIANB,IEX,INDHOTEL,IOC,IRCTC,INDOCO,IGL,INDUSTOWER,INFIBEAM,NAUKRI,INFY,INGERRAND,INOXLEISUR,INTELLECT,INDIGO,IPCALAB,JBCHEPHARM,JKLAKSHMI,JKPAPER,JKTYRE,JMFINANCIL,JSWENERGY,JAMNAAUTO,JINDALSAW,JSLHISAR,JINDALSTEL,JCHAC,JUBLFOOD,JUSTDIAL,KEI,KPITTECH,KRBL,KSB,KAJARIACER,KALPATPOWR,KANSAINER,KARURVYSYA,KEC,KOTAKBANK,L&TFH,LTTS,LAOPALA,LAXMIMACH,LTI,LT,LAURUSLABS,LEMONTREE,LUPIN,MASFIN,MRF,MGL,MAHSCOOTER,M&MFIN,M&M,MAHLOG,MRPL,MARICO,MARUTI,MFSL,MAXHEALTH,MAZDOCK,METROPOLIS,MINDTREE,MINDACORP,MINDAIND,MIDHANI,MOTILALOFS,MCX,NATCOPHARM,NBCC,NCC,NESCO,NHPC,NLCINDIA,NMDC,NTPC,NH,NATIONALUM,NFL,NAVINFLUOR,NESTLEIND,OBEROIRLTY,ONGC,OIL,OFSS,ORIENTELEC,PIIND,PNBHOUSING,PVR,PAGEIND,PERSISTENT,PETRONET,PFIZER,PHILIPCARB,PHOENIXLTD,PIDILITIND,PEL,POLYPLEX,POWERGRID,PRESTIGE,PRINCEPIPE,PRSMJOHNSN,PGHL,PGHH,PNB,RBLBANK,RECLTD,RHIM,RITES,RADICO,RVNL,RAJESHEXPO,RALLIS,RCF,RATNAMANI,RAYMOND,REDINGTON,RELAXO,RELIANCE,RESPONIND,SBICARD,SBILIFE,SIS,SJVN,SKFINDIA,SRF,SANOFI,SCHAEFFLER,SEQUENT,SFL,SCI,SHREECEM,SHRIRAMCIT,SRTRANSFIN,SIEMENS,SOLARINDS,SONATSOFTW,SPICEJET,STARCEMENT,SBIN,SAIL,SWSOLAR,STLTECH,STAR,SUDARSCHEM,SUMICHEM,SPARC,SUNTV,SUNCLAYLTD,SUNDRMFAST,SUNTECK,SUPREMEIND,SUPPETRO,SUVENPHAR,SWANENERGY,SYNGENE,TCNSBRANDS,TTKPRESTIG,TV18BRDCST,TVSMOTOR,TANLA,TASTYBITE,TATACHEM,TATACOFFEE,TATACOMM,TCS,TATACONSUM,TATAELXSI,TATAINVEST,TATAMTRDVR,TATAPOWER,TATASTEEL,TECHM,NIACL,RAMCOCEM,THERMAX,THYROCARE,TITAN,TORNTPHARM,TORNTPOWER,TRENT,UCOBANK,UFLEX,UTIAMC,UJJIVAN,UJJIVANSFB,ULTRACEMCO,UNIONBANK,UBL,MCDOWELL-N,VGUARD,VMART,VIPIND,VSTIND,VAKRANGEE,VARROC,VBL,VOLTAS,WESTLIFE,WHIRLPOOL,WIPRO,ZEEL,ZENSARTECH,ZYDUSWELL,ECLERX';
                let validNames='AARTIIND,ABB,ABBOTINDIA,ABCAPITAL,ABFRL,ACC,ADANIENT,ADANIPORTS,ALKEM,AMBUJACEM,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASIANPAINT,ASTRAL,ATUL,AUBANK,AUROPHARMA,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKNIFTY,BATAINDIA,BEL,BERGEPAINT,BHARATFORG,BHARTIARTL,BHEL,BIOCON,BOSCHLTD,BPCL,BRITANNIA,BSOFT,CANBK,CANFINHOME,CHAMBLFERT,CHOLAFIN,CIPLA,COALINDIA,COFORGE,COLPAL,CONCOR,COROMANDEL,CROMPTON,CUB,CUMMINSIND,DABUR,DALBHARAT,DEEPAKNTR,DELTACORP,DIVISLAB,DIXON,DLF,DRREDDY,EICHERMOT,ESCORTS,EXIDEIND,FEDERALBNK,FINNIFTY,GAIL,GLENMARK,GMRINFRA,GNFC,GODREJCP,GODREJPROP,GRANULES,GRASIM,GUJGASLTD,HAL,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,ICICIGI,ICICIPRULI,IDEA,IDFC,IDFCFIRSTB,IEX,IGL,INDHOTEL,INDIACEM,INDIAMART,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,IPCALAB,IRCTC,ITC,JINDALSTEL,JKCEMENT,JSWSTEEL,JUBLFOOD,KOTAKBANK,L&TFH,LALPATHLAB,LAURUSLABS,LICHSGFIN,LT,LTIM,LTTS,LUPIN,M&M,MANAPPURAM,MARICO,MARUTI,MCDOWELL-N,MCX,METROPOLIS,MFSL,MGL,MOTHERSON,MPHASIS,MRF,MUTHOOTFIN,NATIONALUM,NAUKRI,NAVINFLUOR,NESTLEIND,NIFTY,NMDC,NTPC,OBEROIRLTY,OFSS,ONGC,PAGEIND,PEL,PERSISTENT,PETRONET,PFC,PIDILITIND,PIIND,PNB,POLYCAB,POWERGRID,PVRINOX,RAMCOCEM,RBLBANK,RECLTD,RELIANCE,SAIL,SBICARD,SBILIFE,SBIN,SHREECEM,SHRIRAMFIN,SIEMENS,SRF,SUNPHARMA,SUNTV,SYNGENE,TATACHEM,TATACOMM,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TORNTPHARM,TRENT,TVSMOTOR,UBL,ULTRACEMCO,UPL,VEDL,VOLTAS,WIPRO,ZEEL,ZYDUSLIFE'
               // let validScripcodes='12159,12162,38490,12471,12474,12549,12551,12555,12557,12558,12620,12623,97054,12624,12625,12632,12644,12652,12654,12658,12666,12058,15601,13106,13124,12844,21175,21176,14732,20227,13171,15674,12095,13691,15675,12124,12125,13035,12117,27781,23004,23005,12870,13696,19709,27785,13447,13338,14032,14033,13364,15678,20787,12183,19711,22672,23197,22705,27786,14061,23204,27796,22454,14065,18790,15120,18791,21651,27798,19876,27799,28407,28419,28444,22471,30466,30473,22472,31607,31608,53324,31647,31657,21941,31660,24779,23252,25206,23253,147120,35892,35893,35898,15480,14923,35899,15162,15163,15904,15973,36429,12561,12563,12564,14941,12570,21266,12589,12591,46095,22465,22634,22639,15683,30070,30143,14731,107492,28113,28133,28134,28159,107506,107512,107513,107514,107515,107516,107523,107524,12853,12854,12861,12863,12869,19066,12875,12877,12879,12885,12900,16865,16866,16876,16877,12697,12698,12702,12709,19115,12715,12716,12737,29030,14738,15104,18573,29031,12258,12259,29969,29970,13786,13788,12755,12759,12763,12765,12771,12772,12773,12774,13794,13824,13829,134140,13830,29981,13833,14797,13834'
                 let validScripcodes='63711,63730'
var client = new FivePaisaClient(conf)
console.log("5 paisa scrapping starting at ",currentHour," : ",currentMinute);


function gethistData(scripcodeTemp){
    console.log("***",scripcodeTemp) 
	//scripcodeTemp='3'
    return new Promise((resolve,reject)=>{
        // eichermot     let scripcodeTemp='910';

        setTimeout(()=>{
            
            client.historicalDataRaw('N', 'D', scripcodeTemp, '1m',dateFrom+" "+timeFrom, dateTo+" "+timeTo).then((data,err)=>{
                let tableInsertDataTemp=[];
                if(err)
                console.log(err);

                if(data){
               
                    data.forEach(item=>{
                        //2021-05-24 00:00:00
                        let date1=item[0].substring(0,10);
                        let time1=item[0].replace("T"," ");
                        if(dateFrom+" "+timeFrom <= time1 && dateFrom+" "+timeTo >= time1){
							//console.log(scripcodeTemp,scripNameMap.get(scripcodeTemp))
                            tableInsertDataTemp.push([scripNameMap.get(scripcodeTemp),item[1],time1,new Date(),new Date(),date1,true]);
                            console.log(scripcodeTemp,scripNameMap.get(scripcodeTemp),item[1],time1,new Date(),new Date(),date1,true);
                        }
                    })

                }else{
                    setTimeout(()=>{

                      
                         gethistData(scripcodeTemp)
                    
                        console_log("imp2","AAAAAAAAAAAAAA",scripcodeTemp)
                    },1000)
                    console.log(err);
                }
                
                if(tableInsertDataTemp.length){
                    //console.log("done with ",scripNameMap.get(scripcodeTemp));
                    //process.stdout.write(scripNameMap.get(scripcodeTemp));
                    resolve(tableInsertDataTemp);
                }else{
                    reject("errror skipping ");
                    console_log("imp2","skipp reason is for stockname= at time=", scripNameMap.get(scripcodeTemp), dateFrom, dateTo,data);
                }




            }).catch(err=>console.log(err));

        },250*Math.floor(Math.random() * 100) + 1);


    })
}

//let a=client.historicalData('n', 'c', '1660', '1m','2021-05-31', '2021-06-01')
// This client object can be used to login multiple users.
//QQZzRuFIOzMwajv0VYYigwZ7WsBhf7W3eqdINBCK0CM=


   client.login("sarangsukumar1@gmail.com", "55paisa_18", "19870214").then((response) => {
//client.login("G4mEFv/dPVhFIk04aCsr5K5YLDnLGC+c/7pJVRp2v9M=", "Jx1GYfkTqq0rATskle5RWg==", "umKfDPY+tl1+5NbMBF6IIA==")

   // console.log(response);
   // CLIENT_CODE = response.data.body.ClientCode;
    client.init(response).then(() => {
        // Fetch holdings, positions or place orders here.
        // Some things to try out are given below.
        //console.log(response);
        let requiredStockNames=validNames.split(",");
        let requiredStockScrips= requiredStockNames.filter((it)=>scripCodeMap.get(it)).map((it=>scripCodeMap.get(it)));
           
        console.log(requiredStockScrips);
		//console.log(validScripcodes);


        var promises = [];
        let completedCtr=0;
        let rowsToInsertArray=[];
		const arr = validScripcodes.split(',')
		console.log(arr);
arr.forEach(stockScripItem=>{
//let completedCtr=0;            
promises.push(
//let completedCtr=0;                
gethistData(stockScripItem)
                    .then((data) => {
                       // insertrows(data);
                        completedCtr++;
                        rowsToInsertArray.push(...data);
                        //console.log("to insert now",completedCtr,"==",requiredStockScrips.length,"?");
                        process.stdout.write("    "+completedCtr+"/"+requiredStockScrips.length);
                        if(completedCtr==requiredStockScrips.length){
                            console.log("Inserting now");
                            insertrows(rowsToInsertArray);
                        }
                    })
                    .catch((error)=> {
                        completedCtr++;
                        console.log('Error: ', error);
                    })
            );
        });
   

    }).catch((err) =>{
        // Oh no :/
        console.log(err)
    })
    
}).catch((err) =>{
    // Oh no :/
    console.log("main err",err)
})
//console.log  ( new Date(dateFrom+" "+timeFrom).toISOString());//
//process.exit(0);
Date.prototype.addMinutes = function(mins) {
    this.setTime(this.getTime() + (mins*60*1000));
    return this;
  }

function getRows(){
    let sqlToGetFirstLookData="select stockname,time from scrapliveangel  where date='"+dateFrom+"' and isvalid !=0 and time between '"+new Date(dateFrom+" "+timeFrom).addMinutes(330).toISOString()+"' and '"+new Date(dateFrom+" "+timeTo).addMinutes(330).toISOString()+"'";

    console.log(sqlToGetFirstLookData);
    return new Promise((resolve,reject)=>{
        executeQueryInSQL(sqlToGetFirstLookData)
        .then((allData1)=>{
            resolve(allData1);
          //console.log("aaaaaaaaa",allData1);
        }).catch(err=>{
            console.log(err);
            reject(err);
        });
    })

}



function executeQueryInSQL(sql) {
    console_log("started query -" + sql + new Date().toLocaleTimeString());


    var connection = mysql.createConnection(mysqlConfig);

    return new Promise((resolve, reject) => {
        connection.query(sql, undefined, function (err, data) {
            if (err) {
                console_log("error in mysqlqqq", err);
                reject(err);
            }
            //  console_log(data);

            console_log("ended query - " + sql + new Date().toLocaleTimeString());

            connection.end(err => {
                if (err)
                    console_log("connection end error")
                console_log("conn ended");
                // resolve(data);
                resolve(data);
            });
           
        });
        /*
        connection.end(err=>{
            if(err){
                console_log("unable to close");
               // reject(err);
            }
           
           
        });
        */
    });

}


function insertToTable(tablename, values, columnlist) {

	
    if (tablename.indexOf("orders") > -1)
        console_log("imp1", "inset to Orders", values)
    return new Promise((resolve, reject) => {
       
        var connection = mysql.createConnection(mysqlConfig);
        let colString = "";
        if (columnlist && columnlist.length) {
            colString = "(" + columnlist.join(",") + ")"
        }
        var sql = "INSERT INTO " + tablename + " " + colString + "  VALUES ?";
        console_log("imp", sql, values[0], values.length);
        connection.connect(function (err) {
            if (err) throw err;
            console_log('connected as id ' + connection.threadId);
        });
        connection.query(sql, [values], function (err, data) {
            if (err) {
                console_log("error in mysqlqqq", err);
                reject(err);
            }
            resolve(data);
            console_log("inserted ha ha" + new Date().toLocaleTimeString());

        });
        connection.end(err => {
            if (err) {
                console_log("unable to close");
                reject(err);
            }


        });
    });


}
//let existingRows=new Set();
let skippedCount=0;

function insertrows(rows){

    if(!existingRows.size){
        let finalRowsToInsert=[];
        getRows().then(rows1=>{

            rows1.forEach(itm=>{
               // stockname,date, time
		//console.log("---------------amr",itm.time.toISOString(),itm.time,"----------------------------");
		//process.exit(0);
                existingRows.add(itm.stockname+"$#"+itm.time.toISOString());
            })
            console.log(existingRows.size);
            rows.forEach(row=>{
                let temp= row[0]+"$#"+new Date(row[2]).toISOString();
                if(!existingRows.has(temp)){
                    finalRowsToInsert.push(row);
                }else{
                   	skippedCount++;
			//console.log("skipping");
                }
            })
            console.log("skippedCount"+skippedCount);
            insertToTable(finalRowsToInsert,0,chunk_size);

        }).catch(err=>console.log(err));
        
        

    }else{
        insertToTable(rows,0,chunk_size);
    }
    
    

    function insertToTable(values,beg,end){
        if(beg>rows.length){
            console.log("done");
            return;
        }
      if(!values || values.length==0){
            console.log("notheing to insert");
            return;
        }
           
        console.log("trying from",beg,"to",end);
       // return new Promise((resolve,reject)=>{
           var mysql      = require('mysql');
           var connection = mysql.createConnection({
             host     : 'localhost',
             user     : 'root',
             password : 'root',
             database : 'markets'
           });
             /*
            CREATE TABLE `markets`.`scrapeddata2` (
     `id` INT NOT NULL AUTO_INCREMENT ,
     `stockname` VARCHAR(15) NULL,
     `price` FLOAT NULL,
     `time` DATETIME NULL,
     `cretime` DATETIME NULL,
     `modtime` DATETIME NULL,
     `date` DATE NULL,
     `isvalid` VARCHAR(5) NULL DEFAULT 'TRUE',
     UNIQUE INDEX `id_UNIQUE` (`id` ASC),
     PRIMARY KEY (`id`));
     */
       // insert into scrapeddata (date)  select LEFT(time, 10) from scrapeddata 
       //select distinct LEFT(time, 10) as date1,count(*),stockname from scrapeddata where time like '2020-04-06%' group by date1,stockname ;
           //
       var sql = "INSERT INTO scrapliveangel  (stockname, price, time,cretime,modtime,date,isvalid) VALUES ?";
       connection.connect(function(err) {
           if (err) {
               console.log("err");
           }
           console.log('connected as id ' + connection.threadId);
         });
       connection.query(sql, [values.filter((it,ind)=>ind>=beg&&ind<=end)], function(err) {
           if (err) {
               console.log("error in mysqlqqq",err);
               //reject(err);
           }
           
           
       });
       connection.end(err=>{
           if(err){
               console.log(err,"unable to close");
               //reject(err);
           }
          
           console.log("inserted from",beg,"to",end);
           insertToTable(rows,end+1,end+chunk_size);
       });
      //  });
     
       }


}
function spawnerFunction(fileFullPath){
    let ls = spawn('node',[ fileFullPath]); // '2020-06-15'

    ls.stdout.on('data', (data) => {
      console.log(`stdout: ${data}`);
    });
    
    ls.stderr.on('data', (data) => {
      console.error(`stderr: ${data}`);
    });
    
    ls.on('close', (code) => {
      console.log(`child process exited with code ${code}`);
     
    });
}

function console_log(...args) {
  //  if (args && args[0] && (args[0] + "").startsWith("imp2"))
        console.log(args);//...args.filter((it,ind)=>ind>0));
}



