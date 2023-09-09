import logging
import os
import objectpath


from yahoo_fantasy_api import game
from cachetools import cached, TTLCache
from datetime import datetime, timedelta


logger = logging.getLogger(__file__)
logger.setLevel(logging.INFO)
logging.disable(logging.DEBUG)


dir_path = os.path.dirname(os.path.realpath(__file__))


class Yahoo:

    oauth = None
    scoring_type = None

    def __init__(self, oauth, league_id, league_type):
        self.oauth = oauth
        self.league_id = league_id
        self.league_type = league_type

    def league(self):
        is_valid = self.oauth.token_is_valid()
        logger.info("Token is valid: {}".format(is_valid))
        if not is_valid:
            self.oauth.refresh_access_token()
        gm = game.Game(self.oauth, self.league_type)
        league = gm.to_league("{}.l.{}".format(gm.game_id(), self.league_id))
        self.scoring_type = league.settings()["scoring_type"]
        return league

    @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_standings(self):
        try:
            standings = []
            for idx, team in enumerate(self.league().standings()):
                outcomes = team["outcome_totals"]
                record = "{}-{}-{}".format(
                    outcomes["wins"], outcomes["losses"], outcomes["ties"]
                )
                standings.append(
                    {
                        "place": str(idx + 1) + ". " + team["name"],
                        "record": record,
                    }
                )
            return standings
        except Exception:
            logger.exception(
                "Error while fetching standings for league {}".format(
                    self.league_id
                )
            )
            return None

    @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_roster(self, team_name):
        team_details = self.league().get_team(team_name)
        if team_details:
            return team_details[team_name].roster(self.league().current_week())
        else:
            return None

    @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_player_details(self, player_name):
        try:
            player = self.league().player_details(player_name)[0]
            player["owner"] = self.get_player_owner(player["player_id"])
            return player
        except Exception:
            logger.exception(
                "Error while fetching player details for player: \
                    {} in league {}".format(
                    player_name, self.league_id
                )
            )
            return None

    @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_player_owner(self, player_id):
        try:
            player_ownership = self.league().ownership([player_id])[
                str(player_id)
            ]
            if "owner_team_name" in player_ownership:
                return player_ownership["owner_team_name"]
            else:
                ownership_map = {
                    "freeagents": "Free Agent",
                    "waivers": "On Waviers",
                }
                return ownership_map.get(
                    player_ownership["ownership_type"], ""
                )
        except Exception:
            logger.exception(
                "Error while fetching ownership for player id: \
                    {} in league {}".format(
                    player_id, self.league_id
                )
            )
            return None

    @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_matchups(self):
        try:
            matchups = objectpath.Tree(self.league().matchups()).execute(
                "$..scoreboard..matchups..matchup..teams"
            )

            details = []
            divider = "--------------------------------------"
            for matchup in matchups:
                team1_details = self.get_matchup_details(matchup["0"]["team"])
                team2_details = self.get_matchup_details(matchup["1"]["team"])
                details.append(
                    {
                        "name": "{} vs {}".format(
                            team1_details["name"], team2_details["name"]
                        ),
                        "value": team1_details["text"]
                        + team2_details["text"]
                        + divider,
                    }
                )
            return str(self.league().current_week()), details
        except Exception:
            logger.exception(
                "Error while fetching matchups for league: {}".format(
                    self.league_id
                )
            )

    def get_matchup_details(self, team):
        team_name = team[0][2]["name"]
        team_details = ""
        if self.scoring_type == "head":
            # handle data for head to head scoring
            team1_actual_points = team[1]["team_points"]["total"]
            team1_projected_points = team[1]["team_projected_points"]["total"]
            if "win_probability" in team[1]:
                team1_win_probability = "{:.0%}".format(
                    team[1]["win_probability"]
                )
                team_details = "***{}*** \n Projected Score: {} \n  \
                            Actual Score: {} \n Win Probability: {} \n".format(
                    team_name,
                    team1_projected_points,
                    team1_actual_points,
                    team1_win_probability,
                )
            else:
                team_details = "***{}*** \n Projected Score: {} \n  \
                            Actual Score: {} \n".format(
                    team_name,
                    team1_projected_points,
                    team1_actual_points,
                )
        else:
            team_details = "***{}*** \n Score: {} \n  \
                            Remaining Games: {} \n \
                                Live Games: {} \n \
                                    Completed Games: {} \n".format(
                team_name,
                team[1]["team_points"]["total"],
                team[1]["team_remaining_games"]["total"]["remaining_games"],
                team[1]["team_remaining_games"]["total"]["live_games"],
                team[1]["team_remaining_games"]["total"]["completed_games"],
            )
        return {"name": team_name, "text": team_details}

    @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_latest_trade(self):
        try:
            for key, values in self.league().teams().items():
                if "is_owned_by_current_login" in values:
                    team = self.league().to_team(key)
                    accepted_trades = list(
                        filter(
                            lambda d: d["status"] == "accepted",
                            team.proposed_trades(),
                        )
                    )
                    if accepted_trades:
                        return accepted_trades[0]
            return
        except Exception:
            logger.exception("Error while fetching latest trade")

    def normalize_trade_data(self, trade_data):
        normalized_data = {
            "transaction_key": trade_data["transaction_key"],
            "transaction_id": trade_data["transaction_id"],
            "type": trade_data["type"],
            "status": trade_data["status"],
            "timestamp": trade_data["timestamp"],
            "trader_team_key": trade_data["trader_team_key"],
            "trader_team_name": trade_data["trader_team_name"],
            "tradee_team_key": trade_data["tradee_team_key"],
            "tradee_team_name": trade_data["tradee_team_name"],
            "player_count": trade_data["players"].get("count", 0),
            "players": [],
        }

        for i in range(normalized_data["player_count"]):
            player_info = trade_data["players"][str(i)]

            player_data = player_info.get("player", [])[0]

            transaction_data = player_info.get("player", [])[1]["transaction_data"]

            player = {
                "player_key": player_data[0]["player_key"],
                "player_id": player_data[1]["player_id"],
                "name": player_data[2]["name"]["full"],
                "team_abbr": player_data[3]["editorial_team_abbr"],
                "display_position": player_data[4]["display_position"],
                "position_type": player_data[5]["position_type"],
                "source_team_name": transaction_data[0].get("source_team_name", ""),
                "destination_team_name": transaction_data[0].get("destination_team_name", ""),
            }

            normalized_data["players"].append(player)

        return normalized_data

    def get_latest_trades(self):
        ts = datetime.now() - timedelta(hours=1)
        transactions = self.league().transactions("trade", "")
        filtered_transactions = [
            t for t in transactions if int(t["timestamp"]) > ts.timestamp() and t["status"] == "successful"
        ]
        logger.info(f'found {transactions.len} trades')
        trades = []
        for transaction in filtered_transactions:
            trades.append(self.normalize_trade_data(transaction))
        return trades

    def get_latest_waiver_transactions(self):
        ts = datetime.now() - timedelta(days=1)
        transactions = self.league().transactions("add,drop", "")
        filtered_transactions = [
            t for t in transactions if int(t["timestamp"]) > ts.timestamp()
        ]
        return filtered_transactions
