#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import socket
import time
import math
import threading
import schedule
import bluetooth
import datetime

import wattchecker
import logging_util

logging_util.configure_logging('logging_config_main.yaml')
logger = logging_util.get_logger(__name__)

lock = threading.Lock()
wattPool = []
wattPoolForKWH = []

def _get_macaddr():
    """Discover WATT CHECKER and get MAC address of it

    Return:
        string: a mac address of WATT CHECKER
    """
    logger.info('Discovering WATT CHECKER...')
    nearby_devices = bluetooth.discover_devices(lookup_names=True)
    for addr, name in nearby_devices:
        if name == 'WATT CHECKER':
            return addr

    raise Exception('Error: Failed to find MAC address of WATT CHECKER')

def _get_port(mac_address):
    """Get port number of RFCOMM protocol
    * Prerequisites: paired to WATT CHECKER with bluetoothctl command.
    
    Args:
        mac_address (string): a MAC address of WATT CHECKER

    Return:
        int: a port number of RFCOMM protocol
    """
    logger.info('Searching RFCOMM service...')
    services = bluetooth.find_service(address=mac_address)
    for s in services:
        if s['protocol'] == 'RFCOMM':
            return s['port']

    raise Exception('Error: Failed to find RFCOMM protocol.')

def search_wattchecker():
    macaddr = _get_macaddr()
    port = _get_port(macaddr)
    return macaddr, port

def connect_wattchecker(mac_address, port):
    while True:
        try:
            logger.info('Connecting to %s %s ...' % (mac_address, port))
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.connect((mac_address, port))
            s.settimeout(3)
        except OSError as e:
            logger.error('Failed to connect to %s %s: %s' % (mac_address, port, e))
            time.sleep(60)
        else:
            return s

def dumpEnergyLog(deviceId, date, power, data_dir):
    import json
    message = {}
    message['device_id'] = deviceId
    message['datetime'] = date.strftime('%Y/%m/%d %H:%M:%S')
    message['power'] = power

    record = {}
    record['topic'] = "energy_log/notify"
    record['message'] = message

    filename = "{0}_{1}.json".format(deviceId, date.strftime('%Y-%m-%dT%H:%M:%S'))
    filepath = os.path.join(data_dir, filename)

    with open(filepath, 'w+') as f:
        json.dump(record, f)

def calcWattOnMinute(config):
    # 秒=0の現在時刻作成
    now = datetime.datetime.now()
    now = datetime.datetime(now.year, now.month, now.day, now.hour, now.minute, 0)

    lock.acquire()
    global wattPool
    global wattPoolForKWH
    logger.debug('wattPool:{0}'.format(wattPool))
    wattMinute = round(0 if len(wattPool) == 0 else sum(wattPool) / len(wattPool), 4)
    wattPoolForKWH.extend(wattPool)
    wattPool = []
    lock.release()

    logger.info('電力:{0}[W]'.format(wattMinute))
    dumpEnergyLog(2, now, wattMinute, config['general']['data_dir'])

def calcKWHOnHalfHour(config):
    now = datetime.datetime.now()
    now = datetime.datetime(now.year, now.month, now.day, now.hour, now.minute, 0)

    lock.acquire()
    global wattPoolForKWH
    logger.debug('wattPoolForKWH:{0}'.format(wattPoolForKWH))
    kwh = round((0 if len(wattPoolForKWH) == 0 else sum(wattPoolForKWH) / len(wattPoolForKWH)) / 1000 * 0.5, 4)
    wattPoolForKWH = []
    lock.release()

    logger.info('30分電力量:{0}[kWh]'.format(kwh))
    dumpEnergyLog(3, now, kwh, config['general']['data_dir'])

def getDataThreadFunc():
    global wattPool
 
    mac_address, port = search_wattchecker()
    s = connect_wattchecker(mac_address, port)

    try:
        logger.info('Initializing...')
        wattchecker.initialize(s)
        
        logger.info('Starting measurement...')
        wattchecker.start_measure(s)
        
        while True:
            try:
                data = wattchecker.get_data(s)
                if data:
                    lock.acquire()
                    wattPool.append(data['W'])
                    lock.release()

                now = time.time()
                time.sleep(math.ceil(now) - now)
            except OSError as e:
                logger.error('Failed to get data: %s' % e)

                s = connect_wattchecker(mac_address, port)

                logger.info('Initializing...')
                wattchecker.initialize(s)
                
                logger.info('Starting measurement...')
                wattchecker.start_measure(s)
    
    except Exception as e:
        logger.error(e)

    finally:
        try:
            logger.info('Stopping measurement...')
            wattchecker.stop_measure(s)

            logger.info('Closing socket...')
            s.close()
        except Exception as e:
            logger.error('Failed to close connection: %s' % e)

def load_config(config_path):
    import yaml
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f.read())
    
    return config

def aparse():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--config', default='config.yaml', type=str,
        help='Path to configuration file.'
    )
    return parser.parse_args()

def main():
    args = aparse()
    config = load_config(os.path.join(os.path.dirname(__file__), args.config))

    # wattCheckerからの電力取得スレッド開始
    getDataThread = threading.Thread(target=getDataThreadFunc)
    getDataThread.start()

    # 毎分00秒で平均電力を算出
    schedule.every(1).minutes.at(":00").do(calcWattOnMinute, config)

    # 毎30分毎に電力量を算出
    schedule.every().hour.at(":00").do(calcKWHOnHalfHour, config)
    schedule.every().hour.at(":30").do(calcKWHOnHalfHour, config)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
