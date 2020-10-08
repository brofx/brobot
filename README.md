# Brobot

This is a discord bot used for our discord server.

## Modules (Cogs)

Modules, also known as cogs in the discord.py module, are used to create individual files which contain commands related to that module.

### Current Modules

TODO: Include arguments and syntaxes

All commands are prefixed with `!`. 

- `good bot` / `bad bot`
    - No prefex, bot will reply in a snarky manner.
- roll
    - Rolls a number between 0 and 100. Takes optional first and second parameters to either define a max (only when first parameter is present) or a range (when both parameters are present).
- stocks
    - Gets current stock information for the provided symbol. Defaults to DJi.
- mock
    - transforms "text like this" to "TexT LiKe THIS"
- f1
    - Gets information on the next F1 race.
- urbandict
    - Get the Urban Dictionary definition of a term.
- rather
    - Gets a random "Would You Rather" question from Reddit.
- choose
    - Will choose an option from the provided options.
- split
    - Will take all users in the current voice channel and split them among that channel and the channel provided.
- 8ball / 8
    - Rolls a magic 8 ball. Optional question can be included
- mentions
    - Shows the top 3 most mentioned users
- lines
    - Shows the top 3 most talkative users
- seen
    - Shows the last message the user said in the main channel
- nubeer
    - Shows stats for nubeer
### Writing Modules

You can view the existing modules in the modules directory to get an idea of how to write a module.

Once you have your module, you can edit `brobot.py` and add it to the list of modules.

