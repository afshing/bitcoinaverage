import email
import json
import time
from decimal import Decimal
import datetime
import eventlet
from eventlet.green import urllib2
from eventlet.green import httplib
from eventlet.timeout import Timeout
import simplejson
import socket

from bitcoinaverage.bitcoinchart_fallback import getData
from bitcoinaverage.config import DEC_PLACES, API_QUERY_FREQUENCY, API_IGNORE_TIMEOUT, API_REQUEST_HEADERS, EXCHANGE_LIST, API_CALL_TIMEOUT_THRESHOLD, CURRENCY_LIST
from bitcoinaverage.exceptions import CallTimeoutException, NoApiException, CacheTimeoutException, NoVolumeException
from bitcoinaverage.helpers import write_log
from bitcoinaverage.server import BITCOIN_DE_API_KEY


API_QUERY_CACHE = {} #holds last calls to APIs and last received data between calls

exchanges_rates = []
exchanges_ignored = {}


def callAll():
    global EXCHANGE_LIST, exchanges_rates, exchanges_ignored
    pool = eventlet.GreenPool()

    exchanges_rates = []
    exchanges_ignored = {}

    for exchange_name, exchange_data, exchange_ignore_reason in pool.imap(callAPI, EXCHANGE_LIST):
        if exchange_ignore_reason is None:
            if exchange_data is not None:
                exchange_data['exchange_name'] = exchange_name
                exchanges_rates.append(exchange_data)
        else:
            exchanges_ignored[exchange_name] = exchange_ignore_reason
    return exchanges_rates, exchanges_ignored


def callAPI(exchange_name):
    global API_QUERY_CACHE, API_QUERY_FREQUENCY, API_IGNORE_TIMEOUT, EXCHANGE_LIST

    current_timestamp = int(time.time())
    result = None
    exchange_ignore_reason = None


    if exchange_name not in API_QUERY_CACHE:
        API_QUERY_CACHE[exchange_name] = {'last_call_timestamp': 0,
                                           'result': None,
                                           'call_fail_count': 0,
                                               }

    if ('ignored' in EXCHANGE_LIST[exchange_name]
        and EXCHANGE_LIST[exchange_name]['ignored'] == True
        and 'ignore_reason' in EXCHANGE_LIST[exchange_name]):
        exchange_ignore_reason = str(EXCHANGE_LIST[exchange_name]['ignore_reason'])
    else:
        try:
            try:
                if (exchange_name in API_QUERY_FREQUENCY
                    and API_QUERY_CACHE[exchange_name]['last_call_timestamp']+API_QUERY_FREQUENCY[exchange_name] > current_timestamp):
                    result = API_QUERY_CACHE[exchange_name]['result']
                else:
                    if '_{exchange_name}ApiCall'.format(exchange_name=exchange_name) in globals():
                        try:
                            result = globals()['_%sApiCall' % exchange_name](**EXCHANGE_LIST[exchange_name])
                            result['data_source'] = 'api'
                        except (
                                KeyError,
                                TypeError,
                                ValueError,
                                simplejson.decoder.JSONDecodeError,
                                socket.error,
                                urllib2.URLError,
                                httplib.BadStatusLine,
                                httplib.IncompleteRead,
                                CallTimeoutException) as error:
                            if 'bitcoincharts_symbols' in EXCHANGE_LIST[exchange_name]:
                                result = getData(EXCHANGE_LIST[exchange_name]['bitcoincharts_symbols'])
                                result['data_source'] = 'bitcoincharts'
                            else:
                                raise error
                    elif 'bitcoincharts_symbols' in EXCHANGE_LIST[exchange_name]:
                                result = getData(EXCHANGE_LIST[exchange_name]['bitcoincharts_symbols'])
                                result['data_source'] = 'bitcoincharts'
                    else:
                        raise NoApiException

                    API_QUERY_CACHE[exchange_name] = {'last_call_timestamp': current_timestamp,
                                                       'result':result,
                                                       'call_fail_count': 0,
                                                       }
            except (
                    KeyError,
                    TypeError,
                    ValueError,
                    socket.error,
                    simplejson.decoder.JSONDecodeError,
                    urllib2.URLError,
                    httplib.IncompleteRead,
                    httplib.BadStatusLine,
                    CallTimeoutException) as error:
                API_QUERY_CACHE[exchange_name]['call_fail_count'] = API_QUERY_CACHE[exchange_name]['call_fail_count'] + 1
                if (API_QUERY_CACHE[exchange_name]['last_call_timestamp']+API_IGNORE_TIMEOUT > current_timestamp):
                    result = API_QUERY_CACHE[exchange_name]['result']
                    result['data_source'] = 'cache'
                    write_log('%s call failed, %s, %s fails in a row, using cache, cache age %ss'
                              % (exchange_name,
                                 type(error).__name__,
                                 str(API_QUERY_CACHE[exchange_name]['call_fail_count']),
                                 str(current_timestamp-API_QUERY_CACHE[exchange_name]['last_call_timestamp']) ),
                              'WARNING')
                else:
                    last_call_datetime = datetime.datetime.fromtimestamp(API_QUERY_CACHE[exchange_name]['last_call_timestamp'])
                    today = datetime.datetime.now()
                    if API_QUERY_CACHE[exchange_name]['last_call_timestamp'] == 0:
                        datetime_str = today.strftime('%H:%M')
                        API_QUERY_CACHE[exchange_name]['last_call_timestamp'] = current_timestamp-API_IGNORE_TIMEOUT
                    elif last_call_datetime.day == today.day and last_call_datetime.month == today.month:
                        datetime_str = last_call_datetime.strftime('%H:%M')
                    else:
                        datetime_str = last_call_datetime.strftime('%d %b, %H:%M')

                    last_call_strdate = 'never'
                    if API_QUERY_CACHE[exchange_name]['last_call_timestamp'] != 0:
                        last_call_strdate = email.utils.formatdate(API_QUERY_CACHE[exchange_name]['last_call_timestamp'])

                    log_message = ('%s call failed, %s, %s fails in a row, last successful call - %s, cache timeout, exchange ignored'
                                   % (exchange_name,
                                      type(error).__name__,
                                      str(API_QUERY_CACHE[exchange_name]['call_fail_count']),
                                      last_call_strdate,
                                        ))
                    write_log(log_message, 'ERROR')
                    exception = CacheTimeoutException()
                    exception.strerror = exception.strerror % datetime_str
                    raise exception
        except (NoApiException, NoVolumeException, CacheTimeoutException) as error:
            exchange_ignore_reason = error.strerror

    return exchange_name, result, exchange_ignore_reason


def _mtgoxApiCall(usd_api_url, eur_api_url, gbp_api_url, cad_api_url, pln_api_url, rub_api_url, aud_api_url, chf_api_url,
                  cny_api_url, dkk_api_url, hkd_api_url, jpy_api_url, nzd_api_url, sgd_api_url, sek_api_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_api_url, headers=API_REQUEST_HEADERS)).read()
        usd_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_api_url, headers=API_REQUEST_HEADERS)).read()
        eur_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=gbp_api_url, headers=API_REQUEST_HEADERS)).read()
        gbp_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=cad_api_url, headers=API_REQUEST_HEADERS)).read()
        cad_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=pln_api_url, headers=API_REQUEST_HEADERS)).read()
        pln_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=rub_api_url, headers=API_REQUEST_HEADERS)).read()
        rub_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=aud_api_url, headers=API_REQUEST_HEADERS)).read()
        aud_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=chf_api_url, headers=API_REQUEST_HEADERS)).read()
        chf_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=cny_api_url, headers=API_REQUEST_HEADERS)).read()
        cny_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=dkk_api_url, headers=API_REQUEST_HEADERS)).read()
        dkk_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=hkd_api_url, headers=API_REQUEST_HEADERS)).read()
        hkd_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=jpy_api_url, headers=API_REQUEST_HEADERS)).read()
        jpy_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=nzd_api_url, headers=API_REQUEST_HEADERS)).read()
        nzd_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=sgd_api_url, headers=API_REQUEST_HEADERS)).read()
        sgd_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=sek_api_url, headers=API_REQUEST_HEADERS)).read()
        sek_result = json.loads(response)

    return {'USD': {'ask': Decimal(usd_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(usd_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(usd_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(usd_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'EUR': {'ask': Decimal(eur_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(eur_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(eur_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(eur_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'GBP': {'ask': Decimal(gbp_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(gbp_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(gbp_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(gbp_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'CAD': {'ask': Decimal(cad_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(cad_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(cad_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(cad_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'PLN': {'ask': Decimal(pln_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(pln_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(pln_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(pln_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'RUB': {'ask': Decimal(rub_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(rub_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(rub_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(rub_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'AUD': {'ask': Decimal(aud_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(aud_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(aud_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(aud_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'CHF': {'ask': Decimal(chf_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(chf_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(chf_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(chf_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'CNY': {'ask': Decimal(cny_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(cny_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(cny_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(cny_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'DKK': {'ask': Decimal(dkk_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(dkk_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(dkk_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(dkk_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'HKD': {'ask': Decimal(hkd_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(hkd_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(hkd_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(hkd_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'JPY': {'ask': Decimal(jpy_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(jpy_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(jpy_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(jpy_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'NZD': {'ask': Decimal(nzd_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(nzd_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(nzd_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(nzd_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'SGD': {'ask': Decimal(sgd_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(sgd_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(sgd_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(sgd_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
            'SEK': {'ask': Decimal(sek_result['data']['sell']['value']).quantize(DEC_PLACES),
                    'bid': Decimal(sek_result['data']['buy']['value']).quantize(DEC_PLACES),
                    'last': Decimal(sek_result['data']['last']['value']).quantize(DEC_PLACES),
                    'volume': Decimal(sek_result['data']['vol']['value']).quantize(DEC_PLACES),
            },
    }


def _bitstampApiCall(api_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=api_url, headers=API_REQUEST_HEADERS)).read()
        result = json.loads(response)

    return {'USD': {'ask': Decimal(result['ask']).quantize(DEC_PLACES),
                    'bid': Decimal(result['bid']).quantize(DEC_PLACES),
                    'last': Decimal(result['last']).quantize(DEC_PLACES),
                    'volume': Decimal(result['volume']).quantize(DEC_PLACES),
    }}

# direct volume calculation gives weird results, bitcoincharts API used for now
#@TODO check with campbx why their API results are incorrect
# def campbxApiCall(api_ticker_url, api_trades_url, *args, **kwargs):
#     ticker_result = requests.get(api_ticker_url, headers=API_REQUEST_HEADERS).json()
#
#     return_data = {'USD': {'ask': Decimal(ticker_result['Best Ask']).quantize(DEC_PLACES),
#                                            'bid': Decimal(ticker_result['Best Bid']).quantize(DEC_PLACES),
#                                            'last': Decimal(ticker_result['Last Trade']).quantize(DEC_PLACES),
#                                            'high': None,
#                                            'low': None,
#                                            }
#                     }
#
#     from_time = int(time.time())-(86400)
#     volume = 0.0
#
#     all_trades_direct = {}
#
#     while True:
#         trades = requests.get(api_trades_url % from_time, headers=API_REQUEST_HEADERS).json()
#         new_from_time = from_time
#         for trade in trades:
#             if trade['Time'] > new_from_time:
#                 all_trades_direct[trade['Order ID']] = {'time': trade['Time'],
#                                                          'volume': trade['Bitcoins'],
#                                                          'price': trade['Price'],
#                                                          }
#                 new_from_time = trade['Time']
#                 volume = volume + float(trade['Bitcoins'])
#
#         if new_from_time == from_time:
#             break
#         else:
#             from_time = new_from_time
#
#     return_data['USD']]['volume'] = Decimal(volume).quantize(DEC_PLACES)
#
#     return return_data


def _btceApiCall(usd_api_url, eur_api_url, rur_api_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_api_url, headers=API_REQUEST_HEADERS)).read()
        usd_result = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_api_url, headers=API_REQUEST_HEADERS)).read()
        eur_result = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=rur_api_url, headers=API_REQUEST_HEADERS)).read()
        rur_result = json.loads(response)

    #dirty hack, BTC-e has a bug in their APIs - buy/sell prices mixed up
    if usd_result['ticker']['sell'] < usd_result['ticker']['buy']:
        temp = usd_result['ticker']['buy']
        usd_result['ticker']['buy'] = usd_result['ticker']['sell']
        usd_result['ticker']['sell'] = temp

    if eur_result['ticker']['sell'] < eur_result['ticker']['buy']:
        temp = eur_result['ticker']['buy']
        eur_result['ticker']['buy'] = eur_result['ticker']['sell']
        eur_result['ticker']['sell'] = temp

    if rur_result['ticker']['sell'] < rur_result['ticker']['buy']:
        temp = rur_result['ticker']['buy']
        rur_result['ticker']['buy'] = rur_result['ticker']['sell']
        rur_result['ticker']['sell'] = temp

    return {'USD': {'ask': Decimal(usd_result['ticker']['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(usd_result['ticker']['buy']).quantize(DEC_PLACES),
                    'last': Decimal(usd_result['ticker']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(usd_result['ticker']['vol_cur']).quantize(DEC_PLACES),
                    },
            'EUR': {'ask': Decimal(eur_result['ticker']['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(eur_result['ticker']['buy']).quantize(DEC_PLACES),
                    'last': Decimal(eur_result['ticker']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(eur_result['ticker']['vol_cur']).quantize(DEC_PLACES),
            },
            'RUB': {'ask': Decimal(rur_result['ticker']['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(rur_result['ticker']['buy']).quantize(DEC_PLACES),
                    'last': Decimal(rur_result['ticker']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(rur_result['ticker']['vol_cur']).quantize(DEC_PLACES),
            }}


def _bitcurexApiCall(eur_ticker_url, eur_trades_url, pln_ticker_url, pln_trades_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_ticker_url, headers=API_REQUEST_HEADERS)).read()
        eur_result = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=pln_ticker_url, headers=API_REQUEST_HEADERS)).read()
        pln_result = json.loads(response)

    last24h_time = int(time.time())-86400  #86400s in 24h
    eur_vol = 0.0

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_trades_url, headers=API_REQUEST_HEADERS)).read()
        eur_volume_result = json.loads(response)
    for trade in eur_volume_result:
        if trade['date'] > last24h_time:
            eur_vol = eur_vol + float(trade['amount'])

    pln_vol = 0.0
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=pln_trades_url, headers=API_REQUEST_HEADERS)).read()
        pln_volume_result = json.loads(response)
    for trade in pln_volume_result:
        if trade['date'] > last24h_time:
            pln_vol = pln_vol + float(trade['amount'])

    return {'EUR': {'ask': Decimal(eur_result['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(eur_result['buy']).quantize(DEC_PLACES),
                    'last': Decimal(eur_result['last']).quantize(DEC_PLACES),
                    'volume': Decimal(eur_vol).quantize(DEC_PLACES),
                    },
            'PLN': {'ask': Decimal(pln_result['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(pln_result['buy']).quantize(DEC_PLACES),
                    'last': Decimal(pln_result['last']).quantize(DEC_PLACES),
                    'volume': Decimal(pln_vol).quantize(DEC_PLACES),
                    },
            }


def _vircurexApiCall(usd_api_url, eur_api_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_api_url, headers=API_REQUEST_HEADERS)).read()
        usd_result = json.loads(response)

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_api_url, headers=API_REQUEST_HEADERS)).read()
        eur_result = json.loads(response)

    return {'USD': {'ask': Decimal(usd_result['lowest_ask']).quantize(DEC_PLACES),
                    'bid': Decimal(usd_result['highest_bid']).quantize(DEC_PLACES),
                    'last': Decimal(usd_result['last_trade']).quantize(DEC_PLACES),
                    'volume': Decimal(usd_result['volume']).quantize(DEC_PLACES),
                    },
            'EUR': {'ask': Decimal(eur_result['lowest_ask']).quantize(DEC_PLACES),
                    'bid': Decimal(eur_result['highest_bid']).quantize(DEC_PLACES),
                    'last': Decimal(eur_result['last_trade']).quantize(DEC_PLACES),
                    'volume': Decimal(eur_result['volume']).quantize(DEC_PLACES),
            },
    }


def _bitbargainApiCall(volume_api_url, ticker_api_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=volume_api_url, headers=API_REQUEST_HEADERS)).read()
        volume_data = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_api_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    if volume_data['response']['vol_24h'] is not None:
        average_btc = Decimal(ticker['response']['GBP']['avg_6h'])
        volume_btc = (Decimal(volume_data['response']['vol_24h']) / average_btc)
    else:
        average_btc = DEC_PLACES
        volume_btc = DEC_PLACES

    return {'GBP': {'ask': average_btc.quantize(DEC_PLACES), #bitbargain is an OTC trader, so ask == last == bid
                    'bid': average_btc.quantize(DEC_PLACES), #bitbargain is an OTC trader, so ask == last == bid
                    'last': average_btc.quantize(DEC_PLACES),
                    'volume': volume_btc.quantize(DEC_PLACES),
                    },
    }


def _localbitcoinsApiCall(api_url, *args, **kwargs):
    def _lbcParseCurrency(result, ticker, currency_code):
        try:
            volume = Decimal(ticker[currency_code]['volume_btc']).quantize(DEC_PLACES)
            if ticker[currency_code]['avg_3h'] is not None:
                rate = Decimal(ticker[currency_code]['avg_3h']).quantize(DEC_PLACES)
            elif ticker[currency_code]['avg_12h'] is not None:
                rate = Decimal(ticker[currency_code]['avg_12h']).quantize(DEC_PLACES)
            elif ticker[currency_code]['avg_24h'] is not None:
                rate = Decimal(ticker[currency_code]['avg_24h']).quantize(DEC_PLACES)
            else:
                rate = None
                volume = None
            result[currency_code]= {'ask': rate,
                                    'bid': rate,
                                    'last': rate,
                                    'volume': volume,
                                    }
        except KeyError as error:
            pass

        return result

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=api_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    for currencyCode in CURRENCY_LIST:
        result = _lbcParseCurrency(result, ticker, currencyCode)

    return result


def _cryptotradeApiCall(usd_api_url, #eur_api_url,
                        *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_api_url, headers=API_REQUEST_HEADERS)).read()
        usd_result = json.loads(response)
    # with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
    #     response = urllib2.urlopen(urllib2.Request(url=eur_api_url, headers=API_REQUEST_HEADERS)).read()
    #     eur_result = json.loads(response)


    return {'USD': {'ask': Decimal(usd_result['data']['min_ask']).quantize(DEC_PLACES),
                    'bid': Decimal(usd_result['data']['max_bid']).quantize(DEC_PLACES),
                    'last': Decimal(usd_result['data']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(usd_result['data']['vol_btc']).quantize(DEC_PLACES),
                                    },
            # 'EUR': {'ask': Decimal(eur_result['data']['min_ask']).quantize(DEC_PLACES),
            #         'bid': Decimal(eur_result['data']['max_bid']).quantize(DEC_PLACES),
            #         'last': Decimal(eur_result['data']['last']).quantize(DEC_PLACES),
            #         'volume': Decimal(eur_result['data']['vol_btc']).quantize(DEC_PLACES),
            #                         },
            }


def _rocktradingApiCall(usd_ticker_url, usd_trades_url,
                        eur_ticker_url, eur_trades_url, *args, **kwargs):
    last24h_time = int(time.time())-86400  #86400s in 24h

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_ticker_url, headers=API_REQUEST_HEADERS)).read()
        usd_ticker_result = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_trades_url, headers=API_REQUEST_HEADERS)).read()
        usd_volume_result = json.loads(response)
    usd_last = 0.0
    usd_vol = 0.0
    for trade in usd_volume_result:
        if trade['date'] > last24h_time:
            usd_vol = usd_vol + float(trade['amount'])
            usd_last = float(trade['price'])

    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_ticker_url, headers=API_REQUEST_HEADERS)).read()
        eur_ticker_result = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_trades_url, headers=API_REQUEST_HEADERS)).read()
        eur_volume_result = json.loads(response)
    eur_last = 0.0
    eur_vol = 0.0
    for trade in eur_volume_result:
        if trade['date'] > last24h_time:
            eur_vol = eur_vol + float(trade['amount'])
            eur_last = float(trade['price'])

    return {
            'USD': {'ask': Decimal(usd_ticker_result['result'][0]['ask']).quantize(DEC_PLACES),
                    'bid': Decimal(usd_ticker_result['result'][0]['bid']).quantize(DEC_PLACES),
                    'last': Decimal(usd_last).quantize(DEC_PLACES),
                    'volume': Decimal(usd_vol).quantize(DEC_PLACES),
                                    },
            'EUR': {'ask': Decimal(eur_ticker_result['result'][0]['ask']).quantize(DEC_PLACES) if eur_ticker_result['result'][0]['ask'] is not None else None,
                    'bid': Decimal(eur_ticker_result['result'][0]['bid']).quantize(DEC_PLACES) if eur_ticker_result['result'][0]['bid'] is not None else None,
                    'last': Decimal(eur_last).quantize(DEC_PLACES),
                    'volume': Decimal(eur_vol).quantize(DEC_PLACES),
                                    },
            }


# def _bitcashApiCall(czk_api_url, *args, **kwargs):
#     with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
#         response = urllib2.urlopen(urllib2.Request(url=czk_api_url, headers=API_REQUEST_HEADERS)).read()
#         czk_result = json.loads(response)
#
#     return {'CZK': {'ask': Decimal(czk_result['data']['sell']['value']).quantize(DEC_PLACES),
#                     'bid': Decimal(czk_result['data']['buy']['value']).quantize(DEC_PLACES),
#                     'last': Decimal(czk_result['data']['last']['value']).quantize(DEC_PLACES),
#                     'volume': Decimal(czk_result['data']['vol']['value']).quantize(DEC_PLACES),
#                     },
#             }


def _intersangoApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        result = json.loads(response)

    #'2' in here is ID for EUR in intersango terms
    return {'EUR': {'ask': Decimal(result['2']['sell']).quantize(DEC_PLACES) if result['2']['sell'] is not None else None,
                    'bid': Decimal(result['2']['buy']).quantize(DEC_PLACES) if result['2']['buy'] is not None else None,
                    'last': Decimal(result['2']['last']).quantize(DEC_PLACES) if result['2']['last'] is not None else None,
                    'volume': Decimal(result['2']['vol']).quantize(DEC_PLACES) if result['2']['vol'] is not None else DEC_PLACES,
                    },
            }


def _bit2cApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    try:
        result['ILS'] = {'ask': Decimal(ticker['l']).quantize(DEC_PLACES),
                         'bid': Decimal(ticker['h']).quantize(DEC_PLACES),
                         'last': Decimal(ticker['ll']).quantize(DEC_PLACES),
                         'volume': Decimal(ticker['a']).quantize(DEC_PLACES),
                        }

    except KeyError as error:
        pass

    return result

def _kapitonApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'SEK': {'ask': Decimal(ticker['ask']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['bid']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['price']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['vol']).quantize(DEC_PLACES),
                    },
            }


def _rmbtbApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    try:
        result['CNY'] = {'ask': Decimal(ticker['ticker']['sell']).quantize(DEC_PLACES),
                        'bid': Decimal(ticker['ticker']['buy']).quantize(DEC_PLACES),
                        'last': Decimal(ticker['ticker']['last']).quantize(DEC_PLACES),
                        'volume': Decimal(ticker['ticker']['vol']).quantize(DEC_PLACES),
                        }
    except KeyError as e:
        pass
    return result


def _btcchinaApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'CNY': {'ask': Decimal(ticker['ticker']['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['ticker']['buy']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['ticker']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['ticker']['vol']).quantize(DEC_PLACES),
                    },
            }


def _fxbtcApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'CNY': {'ask': Decimal(ticker['ticker']['ask']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['ticker']['bid']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['ticker']['last_rate']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['ticker']['vol']).quantize(DEC_PLACES),
                    },
            }


def _bterApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'CNY': {'ask': Decimal(ticker['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['buy']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['last']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['vol_btc']).quantize(DEC_PLACES),
                    },
            }


def _goxbtcApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'CNY': {'ask': Decimal(ticker['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['buy']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['last']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['vol']).quantize(DEC_PLACES),
                    },
            }


def _okcoinApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'CNY': {'ask': Decimal(ticker['ticker']['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['ticker']['buy']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['ticker']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['ticker']['vol']).quantize(DEC_PLACES),
                    },
            }


def _mercadoApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'BRL': {'ask': Decimal(ticker['ticker']['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['ticker']['buy']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['ticker']['last']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['ticker']['vol']).quantize(DEC_PLACES),
                    },
            }


def _bitxApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'ZAR': {'ask': Decimal(ticker['ask']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['bid']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['last_trade']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['rolling_24_hour_volume']).quantize(DEC_PLACES),
                    },
            }


def _btctradeApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    return {'CNY': {'ask': Decimal(ticker['sell']).quantize(DEC_PLACES),
                    'bid': Decimal(ticker['buy']).quantize(DEC_PLACES),
                    'last': Decimal(ticker['last']).quantize(DEC_PLACES),
                    'volume': Decimal(ticker['vol']).quantize(DEC_PLACES),
                    },
            }


def _justcoinApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    for currency_data in ticker:
        if currency_data['id'] == 'BTCUSD':
            result['USD'] = {'ask': Decimal(currency_data['ask']).quantize(DEC_PLACES) if currency_data['ask'] is not None else None,
                             'bid': Decimal(currency_data['bid']).quantize(DEC_PLACES) if currency_data['bid'] is not None else None,
                             'last': Decimal(currency_data['last']).quantize(DEC_PLACES) if currency_data['last'] is not None else None,
                             'volume': Decimal(currency_data['volume']).quantize(DEC_PLACES) if currency_data['volume'] is not None else DEC_PLACES,
                             }
        if currency_data['id'] == 'BTCEUR':
            result['EUR'] = {'ask': Decimal(currency_data['ask']).quantize(DEC_PLACES) if currency_data['ask'] is not None else None,
                             'bid': Decimal(currency_data['bid']).quantize(DEC_PLACES) if currency_data['bid'] is not None else None,
                             'last': Decimal(currency_data['last']).quantize(DEC_PLACES) if currency_data['last'] is not None else None,
                             'volume': Decimal(currency_data['volume']).quantize(DEC_PLACES) if currency_data['volume'] is not None else DEC_PLACES,
                             }
        if currency_data['id'] == 'BTCNOK':
            result['NOK'] = {'ask': Decimal(currency_data['ask']).quantize(DEC_PLACES) if currency_data['ask'] is not None else None,
                             'bid': Decimal(currency_data['bid']).quantize(DEC_PLACES) if currency_data['bid'] is not None else None,
                             'last': Decimal(currency_data['last']).quantize(DEC_PLACES) if currency_data['last'] is not None else None,
                             'volume': Decimal(currency_data['volume']).quantize(DEC_PLACES) if currency_data['volume'] is not None else DEC_PLACES,
                             }

    return result


def _krakenApiCall(usd_ticker_url, eur_ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        usd_response = urllib2.urlopen(urllib2.Request(url=usd_ticker_url, headers=API_REQUEST_HEADERS)).read()
        usd_ticker = json.loads(usd_response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        eur_response = urllib2.urlopen(urllib2.Request(url=eur_ticker_url, headers=API_REQUEST_HEADERS)).read()
        eur_ticker = json.loads(eur_response)

    result = {}
    result['USD'] = {'ask': Decimal(usd_ticker['result']['XXBTZUSD']['a'][0]).quantize(DEC_PLACES),
                     'bid': Decimal(usd_ticker['result']['XXBTZUSD']['b'][0]).quantize(DEC_PLACES),
                     'last': Decimal(usd_ticker['result']['XXBTZUSD']['c'][0]).quantize(DEC_PLACES),
                     'volume': Decimal(usd_ticker['result']['XXBTZUSD']['v'][1]).quantize(DEC_PLACES),
                     }
    result['EUR'] = {'ask': Decimal(eur_ticker['result']['XXBTZEUR']['a'][0]).quantize(DEC_PLACES),
                     'bid': Decimal(eur_ticker['result']['XXBTZEUR']['b'][0]).quantize(DEC_PLACES),
                     'last': Decimal(eur_ticker['result']['XXBTZEUR']['c'][0]).quantize(DEC_PLACES),
                     'volume': Decimal(eur_ticker['result']['XXBTZEUR']['v'][1]).quantize(DEC_PLACES),
                     }
    return result


def _bitkonanApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    result['USD'] = {'ask': Decimal(ticker['ask']).quantize(DEC_PLACES),
                     'bid': Decimal(ticker['bid']).quantize(DEC_PLACES),
                     'last': Decimal(ticker['last']).quantize(DEC_PLACES),
                     'volume': Decimal(ticker['volume']).quantize(DEC_PLACES),
                     }
    return result


def _bittyliciousApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    try:
        volume = Decimal(ticker['GBPBTC']['volume_24h']).quantize(DEC_PLACES)
        if ticker['GBPBTC']['avg_6h'] is not None:
            rate = Decimal(ticker['GBPBTC']['avg_6h']).quantize(DEC_PLACES)
        elif ticker['GBPBTC']['avg_12h'] is not None:
            rate = Decimal(ticker['GBPBTC']['avg_12h']).quantize(DEC_PLACES)
        elif ticker['GBPBTC']['avg_24h'] is not None:
            rate = Decimal(ticker['GBPBTC']['avg_24h']).quantize(DEC_PLACES)
        else:
            rate = None
            volume = None
        result['GBP']= {'ask': rate,
                        'bid': rate,
                        'last': rate,
                        'volume': volume,
                        }
    except KeyError as error:
        pass

    return result


def _bitxfApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    result['CNY'] = {'ask': Decimal(ticker['sell']).quantize(DEC_PLACES),
                     'bid': Decimal(ticker['buy']).quantize(DEC_PLACES),
                     'last': Decimal(ticker['last_trade']['price']).quantize(DEC_PLACES),
                     'volume': Decimal(ticker['volume']).quantize(DEC_PLACES),
                     }

    return result


def _cavirtexApiCall(ticker_url, orderbook_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=orderbook_url, headers=API_REQUEST_HEADERS)).read()
        orderbook = json.loads(response)


    bid = 0
    for bid_order in orderbook['bids']:
        if bid < bid_order[0] or bid == 0:
            bid = bid_order[0]

    ask = 0
    for ask_order in orderbook['asks']:
        if ask > ask_order[0] or ask == 0:
            ask = ask_order[0]

    bid = Decimal(bid).quantize(DEC_PLACES)
    ask = Decimal(ask).quantize(DEC_PLACES)
    result = {}
    result['CAD'] = {'ask': ask,
                     'bid': bid,
                     'last': Decimal(ticker['last']).quantize(DEC_PLACES),
                     'volume': Decimal(ticker['volume']).quantize(DEC_PLACES),
                     }

    return result


def _bitfinexApiCall(ticker_url, trades_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=trades_url, headers=API_REQUEST_HEADERS)).read()
        trades = json.loads(response)

    volume = DEC_PLACES
    last24h_timestamp = time.time() - 86400
    for trade in trades:
        if trade['exchange'] == 'bitfinex' and trade['timestamp'] >= last24h_timestamp:
            volume = volume + Decimal(trade['amount'])

    volume = volume.quantize(DEC_PLACES)

    result = {}
    result['USD'] = {'ask': Decimal(ticker['ask']).quantize(DEC_PLACES),
                     'bid': Decimal(ticker['bid']).quantize(DEC_PLACES),
                     'last': Decimal(ticker['last_price']).quantize(DEC_PLACES),
                     'volume': volume,
                     }

    return result


def _fybsgApiCall(ticker_url, trades_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=trades_url, headers=API_REQUEST_HEADERS)).read()
        trades = json.loads(response)

    ask = Decimal(ticker['ask']).quantize(DEC_PLACES)
    bid = Decimal(ticker['bid']).quantize(DEC_PLACES)

    volume = DEC_PLACES
    last24h_timestamp = time.time() - 86400
    last_price = 0
    last_trade_timestamp = 0
    for trade in trades:
        if trade['date'] >= last24h_timestamp:
            volume = volume + Decimal(trade['amount'])
        if trade['date'] > last_trade_timestamp:
            last_trade_timestamp = trade['date']
            last_price = trade['price']
    last_price = Decimal(last_price).quantize(DEC_PLACES)

    result = {}
    result['SGD'] = {'ask': ask,
                     'bid': bid,
                     'last': last_price,
                     'volume': volume,
                     }

    return result


def _fybseApiCall(ticker_url, trades_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=trades_url, headers=API_REQUEST_HEADERS)).read()
        trades = json.loads(response)

    ask = Decimal(ticker['ask']).quantize(DEC_PLACES)
    bid = Decimal(ticker['bid']).quantize(DEC_PLACES)

    volume = DEC_PLACES
    last24h_timestamp = time.time() - 86400
    last_price = 0
    last_trade_timestamp = 0
    for trade in trades:
        if trade['date'] >= last24h_timestamp:
            volume = volume + Decimal(trade['amount'])
        if trade['date'] > last_trade_timestamp:
            last_trade_timestamp = trade['date']
            last_price = trade['price']
    last_price = Decimal(last_price).quantize(DEC_PLACES)

    result = {}
    result['SEK'] = {'ask': ask,
                     'bid': bid,
                     'last': last_price,
                     'volume': volume,
                     }
    return result


def _bitcoin_deApiCall(rates_url, trades_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        rates_url = rates_url.format(api_key=BITCOIN_DE_API_KEY)
        response = urllib2.urlopen(urllib2.Request(url=rates_url, headers=API_REQUEST_HEADERS)).read()
        rates = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        trades_url = trades_url.format(api_key=BITCOIN_DE_API_KEY)
        response = urllib2.urlopen(urllib2.Request(url=trades_url, headers=API_REQUEST_HEADERS)).read()
        trades = json.loads(response)

    result = {}
    if 'rate_weighted_3h' in rates:
        last_avg_price = Decimal(rates['rate_weighted_3h']).quantize(DEC_PLACES)
    elif 'rate_weighted_12h' in rates:
        last_avg_price = Decimal(rates['rate_weighted_12h']).quantize(DEC_PLACES)
    else:
        return result


    volume = DEC_PLACES
    last24h_timestamp = time.time() - 86400
    for trade in trades:
        if trade['date'] >= last24h_timestamp:
            volume = volume + Decimal(trade['amount'])

    result['EUR'] = {'ask': last_avg_price,
                     'bid': last_avg_price,
                     'last': last_avg_price,
                     'volume': volume,
                     }

    return result


def _itbitApiCall(usd_url, eur_url, sgd_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=usd_url, headers=API_REQUEST_HEADERS)).read()
        usd_rates = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=eur_url, headers=API_REQUEST_HEADERS)).read()
        eur_trades = json.loads(response)
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=sgd_url, headers=API_REQUEST_HEADERS)).read()
        sgd_trades = json.loads(response)

    result = {}
    if usd_rates['volume'] > 0:
        result['USD'] = {'ask': Decimal(usd_rates['ask']).quantize(DEC_PLACES),
                         'bid': Decimal(usd_rates['bid']).quantize(DEC_PLACES),
                         'last': Decimal(usd_rates['close']).quantize(DEC_PLACES),
                         'volume': Decimal(usd_rates['volume']).quantize(DEC_PLACES),
                         }
    if eur_trades['volume'] > 0:
        result['EUR'] = {'ask': Decimal(eur_trades['ask']).quantize(DEC_PLACES),
                         'bid': Decimal(eur_trades['bid']).quantize(DEC_PLACES),
                         'last': Decimal(eur_trades['close']).quantize(DEC_PLACES),
                         'volume': Decimal(eur_trades['volume']).quantize(DEC_PLACES),
                         }
    if sgd_trades['volume'] > 0:
        result['SGD'] = {'ask': Decimal(sgd_trades['ask']).quantize(DEC_PLACES),
                         'bid': Decimal(sgd_trades['bid']).quantize(DEC_PLACES),
                         'last': Decimal(sgd_trades['close']).quantize(DEC_PLACES),
                         'volume': Decimal(sgd_trades['volume']).quantize(DEC_PLACES),
                         }

    return result


def _bitcoin_centralApiCall(ticker_url, depth_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    result['EUR'] = {'ask': Decimal(ticker['ask']).quantize(DEC_PLACES),
                     'bid': Decimal(ticker['bid']).quantize(DEC_PLACES),
                     'last': Decimal(ticker['price']).quantize(DEC_PLACES),
                     'volume': Decimal(ticker['volume']).quantize(DEC_PLACES),
                     }
    return result


def _btcturkApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    result['TRY'] = {'ask': Decimal(ticker['ask']).quantize(DEC_PLACES),
                     'bid': Decimal(ticker['bid']).quantize(DEC_PLACES),
                     'last': Decimal(ticker['last']).quantize(DEC_PLACES),
                     'volume': Decimal(ticker['volume']).quantize(DEC_PLACES),
                     }
    return result


def _bitonicApiCall(ticker_url, *args, **kwargs):
    with Timeout(API_CALL_TIMEOUT_THRESHOLD, CallTimeoutException):
        response = urllib2.urlopen(urllib2.Request(url=ticker_url, headers=API_REQUEST_HEADERS)).read()
        ticker = json.loads(response)

    result = {}
    result['EUR'] = {'ask': Decimal(ticker['price']).quantize(DEC_PLACES),
                     'bid': Decimal(ticker['price']).quantize(DEC_PLACES),
                     'last': Decimal(ticker['price']).quantize(DEC_PLACES),
                     'volume': Decimal(ticker['volume']).quantize(DEC_PLACES),
                     }
    return result
