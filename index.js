//var fs = require('fs');
const Discord = require('discord.js');
const client = new Discord.Client();




const sleep = (milliseconds) => {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

client.once('ready', () => {
    console.log('Ready!');
  //  require("./plugins.js").init(hooks);
});



// set message listener 
client.on('error', error => {
// get exact error logged to the console
            console.log(error);
//reset the bot 
            resetBot();
    
});

// Turn bot off (destroy), then turn it back on
function resetBot() {
    client.destroy()
    .then(() => client.login('NTUyMTkxNzY2MDAzMDU2NjUw.D2QqOg.AJYxsfO0q8A8ged_-WcqCOazkvA'));
}




client.on('message', message => {
	if (message.content === '!ping') {
		message.channel.send('Pong.');
	}
});

client.on('message', message => {
    var lower = message.content.toLowerCase();
    if (lower.includes("brobot") && lower.includes("fuck")) {
        message.channel.send('Do you kiss your mother with that mouth?');
    }
});


client.on('message', message => {
    var color = message.content;
    if (color.startsWith("!color")) {
        if (message.content != "!color list") {

            teams = ["Team Green", "Team Purple", "Team Red", "Team Blue", "Team Yellow", "Team Orange", "Team White", "Team Pink"];

            for (var i = teams.length - 1; i >= 0; i--) {
                var role = message.guild.roles.find(role => role.name === teams[i]);
                message.member.removeRole(role);
            }
        }
        sleep(200).then(() => {
            switch (message.content) {
                case "!color green":
                    role = message.guild.roles.find(role => role.name === "Team Green");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Green!');
                    break;
                case "!color pink":
                    role = message.guild.roles.find(role => role.name === "Team Pink");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Pink!');
                    break;
                case "!color purple":
                    role = message.guild.roles.find(role => role.name === "Team Purple");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Purple!');
                    break;
                case "!color red":
                    role = message.guild.roles.find(role => role.name === "Team Red");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Red!');
                    break;
                case "!color blue":
                    role = message.guild.roles.find(role => role.name === "Team Blue");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Blue!');
                    break;
                case "!color yellow":
                    role = message.guild.roles.find(role => role.name === "Team Yellow");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Yellow!');
                    break;
                case "!color orange":
                    role = message.guild.roles.find(role => role.name === "Team Orange");
                    message.member.addRole(role);
                    message.channel.send('Added to Team Orange!');
                    break;
                case "!color white":
                    role = message.guild.roles.find(role => role.name === "Team White");
                    message.member.addRole(role);
                    message.channel.send('Added to Team White');
                    break;
                case "!color list":
                    message.channel.send('You can select: Red, Orange, Yellow, Green, Blue, Purple, White');
                    break;
                default:
                    message.channel.send("Pick a different Color...");
                    break;
            }
        })
    }
});









// Create an event listener for messages
client.on('message', message => {
  // If the message is "what is my avatar"
  if (message.content === 'what is my avatar') {
    // Send the user's avatar URL
    message.reply(message.author.avatarURL);
  }
});







client.login();
