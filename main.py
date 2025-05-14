import asyncio
import logging
import sys

from aiogram import Bot ,Dispatcher
from aiogram .enums import ParseMode
from dotenv import load_dotenv


from bot .main_bot import run_bot
from config .settings import get_settings ,Settings
from db .database import init_db





async def main ():
    load_dotenv ()
    settings =get_settings ()


    await init_db ()







    await run_bot (settings )


if __name__ =="__main__":
    logging .basicConfig (level =logging .INFO ,stream =sys .stdout ,
    format ='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    try :
        asyncio .run (main ())
    except (KeyboardInterrupt ,SystemExit ):
        logging .info ("Bot stopped manually")