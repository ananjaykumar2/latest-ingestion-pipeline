#!/usr/bin/python3
# redis-client-reader.py

import asyncio
import json
from aio_pika import connect_robust, Message, IncomingMessage, AMQPException
import hashlib
import concurrent.futures

# declaring global because of stupid Futures
# Have to figure out a better method in python to handle all this
# Class defination is the way forward- refactoring
global rg_dict
global data_redis_q
global latest_exchange
routing_key = "#"

async def on_message(message: IncomingMessage):
    print('> *****Inside key_generator*****')
    global data_redis_q, rg_dict
    
    data_redis_q = {}

    # data_dict is actual adapter packet
    data_dict = json.loads(message.body.decode())
    # default value is for all aqm/flood type sensors
    default = '_d'

    # extract resource-group from the data packet
    res_id = data_dict['id']
    rg = res_id.split('/')[3]

    # generate the SHA1 of the id
    sha_id = hashlib.sha1(res_id.encode())
    
    # print("> RG from data---- " + rg)
    # print("> rg_dict---- " + str(rg_dict))
    # print("> SHA1[res_id]---- " + sha_id.hexdigest())
    
    # Check if _rg is present in rg_dict{}
    if rg in rg_dict.keys():
        print('> RG is present.')
        
        # encode SHA1 of resource-id
        attribute = rg_dict[rg]
        path_param = '_' + sha_id.hexdigest() + '_' + data_dict[attribute]
    else:
        print('> RG is not present.')
        path_param = '_' + sha_id.hexdigest() + '_' + default
    
    # generate a dict = { 'key' : <resource-group-name>, 'path_param': <_SHA1(id)_attr/d>, 'data': adapter packet }
    data_redis_q['key'] = rg.replace('-','_');
    data_redis_q['path_param'] = path_param
    data_redis_q['data'] = data_dict

    # print('> (on_message) routing_key---- '+routing_key)
    
    # publish the data into redis-ingestion-queue
    print('> bool(data_redis_q):---- '+str(bool(data_redis_q)))
    if data_redis_q is not None and bool(data_redis_q):
        await latest_exchange.publish(message=Message((json.dumps(data_redis_q)).encode()), routing_key=routing_key)
        print('> Message published.')
        # message.ack()
    else:
        # do nothing
        pass
    message.ack()
async def main_loop(loop):
    global rg_dict, latest_exchange, routing_key 
    data_redis_q={}
    
    # load the dictionary using the config file
    # Needs to change into a Config Retriever, proabably docker configs
    with open('attribute_list.json') as rg_json_f:
        rg_dict = json.load(rg_json_f)
    print('> RG is loaded: ' + str(rg_dict))

    try:
        # Connect to RabbitMQ
        # Can use connection pool instead of two separate clients
        # Have to use docker configs for retrieving redis-user credentials
        rmq_sub_con = await connect_robust(host='0.0.0.0',port=29042,login='redis-user',
                                                       password='uv)aqcY]qSvARi74', virtualhost='IUDX',loop=loop
        )
    except AMQPException as error:
        print('> Connection Failed!')
        error.printStackTrace()
        return

    rmq_q_name = "redis-latest"
    redis_q_name = "redis-ingestion-queue"
    rmq_latest_exchange = "redis-latest-ex"
    async with rmq_sub_con:
        channel = await rmq_sub_con.channel()
        queue_rmq = await channel.declare_queue(rmq_q_name, durable=True, arguments={'x-max-length':20000})
        queue_redis = await channel.declare_queue(redis_q_name, durable=True)

        # declare an exchange to push {data} generated by Key generator for consumption by redis_queue
        latest_exchange = await channel.declare_exchange(rmq_latest_exchange, "direct", durable=True)

        # print('> (Main Loop) Routing key---- '+routing_key)
        
        # bind this latest_exchange to redis_queue
        await queue_redis.bind(latest_exchange, routing_key)
        
        # consume the message from redis-latest queue
        await queue_rmq.consume(on_message)
        
if __name__ == '__main__':
    print('> Running v0.0.1 Redis Client reader.')

    # write the asyncio part
    loop = asyncio.get_event_loop()
    loop.create_task(main_loop(loop))
    loop.run_forever()
