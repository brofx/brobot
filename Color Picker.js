client.on('message', message => {
    var color = message.content;
    if (color.startsWith("!color")) {
        if (message.content != "!color list") {

            teams = ["Team Green", "Team Purple", "Team Red", "Team Blue", "Team Yellow", "Team Orange", "Team White"];

            for (var i = teams.length - 1; i >= 0; i--) {
                var role = message.guild.roles.find(role => role.name === teams[i]);
                message.member.removeRole(role)
                    .then(console.log)
                    .catch(console.error);
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
