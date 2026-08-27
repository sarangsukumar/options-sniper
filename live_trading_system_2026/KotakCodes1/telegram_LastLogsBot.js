
let fileName = "telegram_log.txt";
const fs = require("fs");
const { Telegraf } = require('telegraf')
let token="1987461647:AAHjpU2oTVn6xvQtK9C8IdVwM2tpQTRCLFM";
const bot = new Telegraf(token)
bot.start((ctx) => {
    console.log(ctx);
    ctx.reply('👍')
});

bot.hears('hi', (ctx) => ctx.reply('Hey there'))
bot.launch()
function sendMessage(msg){
    bot.telegram.sendMessage(-1001547510510, msg).then((msg)=> {bot.stop('SIGINT');console.log("then",msg)} ).catch(e=>console.log(e))

}

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'))
process.once('SIGTERM', () => bot.stop('SIGTERM'))

const { exec } = require("child_process");
exec("tail -50 logfile.txt",  (error, stdout, stderr) => {
console.log(stdout);
Write_File_For_Telegram(stdout);

exec("cut -c-75 telegram_log.txt",  (error, stdout, stderr) => {

sendMessage(stdout.substring(0,4090));
   
})
   
})

function Write_File_For_Telegram(text)
{
	fs.writeFileSync(fileName, text, {
  encoding: 'utf8',
  flag: 'w'
})

}