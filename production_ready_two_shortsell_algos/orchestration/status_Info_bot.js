let fileName="status_critical.txt";
var fs = require('fs');
const { exec } = require("child_process");
const { Telegraf } = require('telegraf')
let token="7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko";
let randdate;
let HourNow;
let MinuteNow;
const bot = new Telegraf(token)

let retrycounter=0;


bot.start((ctx) => {
    console.log(ctx);
    ctx.reply('👍');
});

bot.hears('hi', (ctx) => ctx.reply('Hey there'));
bot.launch();

function sendMessage(msg){
    console.log(msg);
    console.log(msg.length);
    if(msg && msg.length > 0) // Added check for null or empty message
    {
        bot.telegram.sendMessage(-1002365534285, msg, { parse_mode: 'HTML' })
            .then((sentMessage) => {
                console.log("Message sent successfully:", sentMessage);
                bot.stop('SIGINT'); // Stop the bot after sending the message
            })
            .catch(e => console.error("Error sending message:", e));
    } else {
        console.log("No message to send.");
        bot.stop('SIGINT'); // Stop even if no message
    }
    return;
}

function appendtofile(text) {
    console.log(text);
    fs.appendFile(fileName, text + "\n", (err) => {
        if (err) console.error("Error appending to file:", err);
    });
}

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));

randdate= new Date();
HourNow=randdate.getHours();
MinuteNow=randdate.getMinutes();
console.log(HourNow,MinuteNow);

randdate= new Date().toISOString().substring(0,10);


// Get the message from the command-line arguments
const messageToSend = process.argv[2];

// Call sendMessage with the command-line argument
if (messageToSend) {
    sendMessage(messageToSend);
} else {
    console.log("Please provide a message as a command-line argument.");
    bot.stop('SIGINT'); // Stop if no message is provided
}