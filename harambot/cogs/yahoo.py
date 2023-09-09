import discord
import logging
import urllib3

from discord.ext import commands, tasks
from discord import app_commands
from yahoo_oauth import OAuth2
from playhouse.shortcuts import model_to_dict
from datetime import datetime, timedelta

from harambot.yahoo_api import Yahoo
from harambot.database.models import Guild


logger = logging.getLogger(__file__)
logger.setLevel(logging.INFO)


class YahooCog(commands.Cog):

    error_message = (
        "I'm having trouble getting that right now please try again later"
    )

    def __init__(self, bot, KEY, SECRET, guild_id=None, channel_id=None):
        self.bot = bot
        self.http = urllib3.PoolManager()
        self.KEY = KEY
        self.SECRET = SECRET
        self.yahoo_api = None
        self.guild_id = guild_id
        self.channel_id = channel_id

    async def cog_before_invoke(self, ctx):
        guild = Guild.get(Guild.guild_id == str(ctx.guild.id))
        self.yahoo_api = Yahoo(
            OAuth2(
                self.KEY, self.SECRET, store_file=False, **model_to_dict(guild)
            ),
            guild.league_id,
            guild.league_type,
        )
        return

    async def set_yahoo_from_interaction(
        self, interaction: discord.Interaction
    ):
        guild = Guild.get(Guild.guild_id == str(interaction.guild_id))
        self.yahoo_api = Yahoo(
            OAuth2(
                self.KEY, self.SECRET, store_file=False, **model_to_dict(guild)
            ),
            guild.league_id,
            guild.league_type,
        )
        logger.info(f"yahoo_api: {self.yahoo_api}")
        self.guild_id = interaction.guild_id
        self.channel_id = interaction.channel_id
        return
    
    async def set_yahoo_from_config(
        self
    ):
        guild = Guild.get(Guild.guild_id == str(self.guild_id))
        self.yahoo_api = Yahoo(
            OAuth2(
                self.KEY, self.SECRET, store_file=False, **model_to_dict(guild)
            ),
            guild.league_id,
            guild.league_type
        )
        return

    @app_commands.command(
        name="standings",
        description="Returns the current standings of your league",
    )
    async def standings(self, interaction: discord.Interaction):
        logger.info("standings called")
        embed = discord.Embed(
            title="Standings",
            description="Team Name\n W-L-T",
            color=0xEEE657,
        )
        await self.set_yahoo_from_interaction(interaction)
        for team in self.yahoo_api.get_standings():
            embed.add_field(
                name=team["place"],
                value=team["record"],
                inline=False,
            )
        if embed:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(self.error_message)

    @app_commands.command(
        name="roster", description="Returns the roster of the given team"
    )
    async def roster(self, interaction: discord.Interaction, team_name: str):
        logger.info("roster called")
        await self.set_yahoo_from_interaction(interaction)
        embed = discord.Embed(
            title="{}'s Roster".format(team_name),
            description="",
            color=0xEEE657,
        )
        roster = self.yahoo_api.get_roster(team_name)
        if roster:
            for player in roster:
                embed.add_field(
                    name=player["selected_position"],
                    value=player["name"],
                    inline=False,
                )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(self.error_message)

    @app_commands.command(
        name="trade",
        description="Create poll for latest trade for league approval",
    )
    async def trade(self, interaction: discord.Interaction):
        logger.info("trade called")
        await self.set_yahoo_from_interaction(interaction)
        latest_trade = self.yahoo_api.get_latest_trade()

        if latest_trade is None:
            await interaction.response.send_message(
                "No trades up for approval at this time"
            )
            return

        teams = self.yahoo_api.league().teams()

        trader = teams[latest_trade["trader_team_key"]]
        tradee = teams[latest_trade["tradee_team_key"]]
        managers = [trader["name"], tradee["name"]]

        player_set0 = []
        player_set0_details = ""
        for player in latest_trade["trader_players"]:
            if player:
                player_set0.append(player["name"])
                api_details = (
                    self.get_player_text(
                        self.yahoo_api.get_player_details(player["name"])
                    )
                    + "\n"
                )
                if api_details:
                    player_set0_details = player_set0_details + api_details
                else:
                    await interaction.send(self.error_message)
                    return

        player_set1 = []
        player_set1_details = ""
        for player in latest_trade["tradee_players"]:
            player_set1.append(player["name"])
            api_details = (
                self.get_player_text(
                    self.yahoo_api.get_player_details(player["name"])
                )
                + "\n"
            )
            if api_details:
                player_set1_details = player_set1_details + api_details
            else:
                await interaction.response.send_message(self.error_message)
                return

            confirm_trade_message = "{} sends {} to {} for {}".format(
                managers[0],
                ", ".join(player_set0),
                managers[1],
                ", ".join(player_set1),
            )
            announcement = "There's collusion afoot!\n"
            embed = discord.Embed(
                title="The following trade is up for approval:",
                description=confirm_trade_message,
                color=0xEEE657,
            )
            embed.add_field(
                name="{} sends:".format(managers[0]),
                value=player_set0_details,
                inline=False,
            )
            embed.add_field(
                name="to {} for:".format(managers[1]),
                value=player_set1_details,
                inline=False,
            )
            embed.add_field(
                name="Voting",
                value=" Click :white_check_mark: for yes,\
                     :no_entry_sign: for no",
            )
            await interaction.response.send_message(
                content=announcement, embed=embed
            )
            response_message = await interaction.original_response()
            yes_emoji = "\U00002705"
            no_emoji = "\U0001F6AB"
            await response_message.add_reaction(yes_emoji)
            await response_message.add_reaction(no_emoji)

    @app_commands.command(
        name="stats", description="Returns the details of the given player"
    )
    async def stats(self, interaction: discord.Interaction, player_name: str):
        logger.info("player_details called")
        await self.set_yahoo_from_interaction(interaction)
        player = self.yahoo_api.get_player_details(player_name)
        if player:
            embed = self.get_player_embed(player)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Player not found")

    def get_player_embed(self, player):
        embed = discord.Embed(
            title=player["name"]["full"],
            description="#" + player["uniform_number"],
            color=0xEEE657,
        )
        embed.add_field(name="Postion", value=player["primary_position"])
        embed.add_field(name="Team", value=player["editorial_team_abbr"])
        if "bye_weeks" in player:
            embed.add_field(name="Bye", value=player["bye_weeks"]["week"])
        if "player_points" in player:
            embed.add_field(
                name="Total Points", value=player["player_points"]["total"]
            )
        embed.add_field(name="Owner", value=player["owner"])
        embed.set_image(url=player["image_url"])
        return embed

    def get_player_text(self, player):
        player_details_text = (
            player["name"]["full"] + " #" + player["uniform_number"] + "\n"
        )
        player_details_text = (
            player_details_text
            + "Position: "
            + player["primary_position"]
            + "\n"
        )
        player_details_text = (
            player_details_text
            + "Team: "
            + player["editorial_team_abbr"]
            + "\n"
        )
        if "bye_weeks" in player:
            player_details_text = (
                player_details_text
                + "Bye: "
                + player["bye_weeks"]["week"]
                + "\n"
            )
        if "player_points" in player:
            player_details_text = (
                player_details_text
                + "Total Points: "
                + player["player_points"]["total"]
                + "\n"
            )
        player_details_text = (
            player_details_text
            + "Owner: "
            + self.yahoo_api.get_player_owner(player["player_id"])
        )
        return player_details_text

    @app_commands.command(
        name="matchups", description="Returns the current weeks matchups"
    )
    async def matchups(self, interaction: discord.Interaction):
        await self.set_yahoo_from_interaction(interaction)
        week, details = self.yahoo_api.get_matchups()
        if details:
            embed = discord.Embed(
                title="Matchups for Week {}".format(week),
                description="",
                color=0xEEE657,
            )
            for detail in details:
                embed.add_field(
                    name=detail["name"], value=detail["value"], inline=False
                )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(self.error_message)

    @app_commands.command(
    name="start-polling", description="sets the yahoo config and starts polling for waivers"
    )
    async def start_polling(self, interaction: discord.Interaction):
        await self.set_yahoo_from_interaction(interaction)
        if self.poll_for_transactions.is_running():
            await interaction.response.send_message('already running', ephemeral=True)
        else:
            self.poll_for_transactions.start()

        if not self.refresh_token.is_running():
            logger.info('starting refresh token')
            self.refresh_token.start()
        
        await interaction.response.send_message('done', ephemeral=True)

    @app_commands.command(
        name="waivers",
        description="Returns the wavier transactions from the last 24 hours",
    )
    async def waivers(self, interaction: discord.Interaction):
        try:

            await self.set_yahoo_from_interaction(interaction)
            await interaction.response.defer(thinking=True)
            embed_functions_dict = {
                "add/drop": self.create_add_drop_embed,
                "add": self.create_add_embed,
                "drop": self.create_drop_embed,
            }
            for transaction in self.yahoo_api.get_latest_waiver_transactions():
                await interaction.followup.send(
                    embed=embed_functions_dict[transaction["type"]](transaction)
                )
        except:
            logger.exception("Error while getting waivers")

    def create_add_embed(self, transaction):
        owner = transaction["players"]["0"]["player"][1]["transaction_data"][0]["destination_team_name"]
        player_id = int(transaction["players"]["0"]["player"][0][1]["player_id"])
        headshot= self.yahoo_api.get_player_details(player_id)["headshot"]["url"]
        embed = discord.Embed(title=f"Player added by {owner}", colour=0x06B900)
        embed.set_thumbnail(url=headshot)
        self.add_player_fields_to_embed(
            embed, transaction["players"]["0"]["player"][0]
        )
        return embed
    


    def create_trade_embed(self, trade):
        trader_team_name = trade["trader_team_name"]
        tradee_team_name = trade["tradee_team_name"]
        embed = discord.Embed(
            title=f"Trade between {trader_team_name} and {tradee_team_name}",
            colour=0xff00ff
        )

        # Separate players into two lists based on destination team
        traders_players = []
        tradees_players = []

        for player in trade["players"]:
            if player["destination_team_name"] == trader_team_name:
                traders_players.append(player)
            elif player["destination_team_name"] == tradee_team_name:
                tradees_players.append(player)

        embed.add_field(
            name=f"Players to {trader_team_name}",
            value="=====================",
            inline=False
        )

        for player in traders_players:
            embed.add_field(
                name="Player", value=player["name"], inline=False
            )
            embed.add_field(
                name="Team", value=player["team_abbr"], inline=False
            )
            embed.add_field(
                name="Position", value=player["display_position"], inline=False
            )
        
        embed.add_field(
            name=f"Players to {tradee_team_name}",
            value="=====================",
            inline=False
        )
        for player in tradees_players:
            embed.add_field(
                name="Player", value=player["name"], inline=False
            )
            embed.add_field(
                name="Team", value=player["team_abbr"], inline=False
            )
            embed.add_field(
                name="Position", value=player["display_position"], inline=False
            )

        return embed

    def create_drop_embed(self, transaction):

        owner = transaction["players"]["0"]["player"][1]["transaction_data"]["source_team_name"]
        player_id = int(transaction["players"]["0"]["player"][0][1]["player_id"])
        headshot= self.yahoo_api.get_player_details(player_id)["headshot"]["url"]
        embed = discord.Embed(title=f"Player dropped by {owner}", colour=0xFF0000)
        embed.set_thumbnail(url=headshot)
        self.add_player_fields_to_embed(
            embed, transaction["players"]["0"]["player"][0]
        )
        return embed

    def create_add_drop_embed(self, transaction):
        owner = transaction["players"]["0"]["player"][1]["transaction_data"][
                0
            ]["destination_team_name"]
    
        player_id = int(transaction["players"]["0"]["player"][0][1]["player_id"])
        headshot= self.yahoo_api.get_player_details(player_id)["headshot"]["url"]
        embed = discord.Embed(title=f"Player added/dropped by {owner}", colour=0xFFFF00)
        embed.set_thumbnail(url=headshot)
        embed.add_field(
            name="Player Added", value="=====================", inline=False
        )
        self.add_player_fields_to_embed(
            embed, transaction["players"]["0"]["player"][0], inline=True
        )
        embed.add_field(
            name="Player Dropped", value="=====================", inline=False
        )
        self.add_player_fields_to_embed(
            embed, transaction["players"]["1"]["player"][0], inline=True
        )
        
        return embed

    def add_player_fields_to_embed(self, embed, player, inline=True):
        embed.add_field(
            name="Player", value=player[2]["name"]["full"], inline=inline
        )
        embed.add_field(
            name="Team", value=player[3]["editorial_team_abbr"], inline=inline
        )
        embed.add_field(
            name="Position", value=player[4]["display_position"], inline=inline
        )

    @tasks.loop(seconds=60.0)
    async def poll_for_transactions(self):
        try:
            logger.info('polling for transactions')
            embed_functions_dict = {
                "add/drop": self.create_add_drop_embed,
                "add": self.create_add_embed,
                "drop": self.create_drop_embed,
                "trade": self.create_trade_embed
            }
            channel = self.bot.get_channel(self.channel_id)
            ts = datetime.now() - timedelta(minutes=1)

            transactions = self.yahoo_api.get_latest_waiver_transactions()
            trades = self.yahoo_api.get_latest_trades()
            transactions.extend(trades)
            logger.info(f"found {len(transactions)} transactions")
            for transaction in transactions:
                logger.debug(f"transaction timestamp: {transaction['timestamp']}, time: {datetime.fromtimestamp(int(transaction['timestamp']))}")
                if int(transaction["timestamp"]) > ts.timestamp():
                    logger.debug(f"sending message to channel: {self.channel_id}")
                    await channel.send(
                        embed=embed_functions_dict[transaction["type"]](transaction)
                    )
        except:
            logger.exception("Error while polling for transactions")

    @tasks.loop(seconds=600.0)
    async def refresh_token(self):
        logger.info('refreshing token')
        try:
            await self.set_yahoo_from_config()
        except:
            logger.exception("Error while refreshing token")