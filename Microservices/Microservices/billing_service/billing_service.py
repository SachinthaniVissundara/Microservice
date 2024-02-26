import json
import logging
import signal
import uuid

from event_store.event_store_client import EventStoreClient, create_event
from message_queue.message_queue_client import Consumers, send_message


class BillingService(object):
    """
    Billing Service class.
    """
    def __init__(self):
        self.event_store = EventStoreClient()
        self.consumers = Consumers('billing-service', [self.create_billings,
                                                       self.update_billing,
                                                       self.delete_billing])

    @staticmethod
    def _create_entity(_order_id, _amount):
        """
        Create a billing entity.

        :param _order_id: The order ID the billing belongs to.
        :param _amount: Total amount to pay.
        :return: A dict with the entity properties.
        """
        return {
            'entity_id': str(uuid.uuid4()),
            'order_id': _order_id,
            'amount': _amount
        }

    @staticmethod
    def _check_amount(_billing):
        rsp = send_message('read-model', 'get_entity', {'name': 'order', 'id': _billing['order_id']})
        order = rsp['result']

        rsp = send_message('read-model', 'get_entity', {'name': 'cart', 'id': order['cart_id']})
        cart = rsp['result']

        rsp = send_message('read-model', 'get_entities', {'name': 'product', 'ids': cart['product_ids']})
        products = rsp['result']

        amount = sum([int(product['price']) for product in products])

        return amount == int(_billing['amount'])

    def start(self):
        logging.info('starting ...')
        self.consumers.start()
        self.consumers.wait()

    def stop(self):
        self.consumers.stop()
        logging.info('stopped.')

    def create_billings(self, _req):
        billings = _req if isinstance(_req, list) else [_req]
        billing_ids = []

        for billing in billings:
            res = self._check_amount(billing)
            if not res:
                return {
                    'error': 'amount is not accurate'
                }

            try:
                new_billing = BillingService._create_entity(billing['order_id'], billing['amount'])
            except KeyError:
                return {
                    "error": "missing mandatory parameter 'order_id' and/or 'amount'"
                }

            # trigger event
            self.event_store.publish('billing', create_event('entity_created', new_billing))

            billing_ids.append(new_billing['entity_id'])

        return {
            "result": billing_ids
        }

    def update_billing(self, _req):
        try:
            billing_id = _req['entity_id']
        except KeyError:
            return {
                "error": "missing mandatory parameter 'entity_id'"
            }

        rsp = send_message('read-model', 'get_entitiy', {'name': 'billing', 'id': billing_id})
        if 'error' in rsp:
            rsp['error'] += ' (from read-model)'
            return rsp

        billing = rsp['result']
        if not billing:
            return {
                "error": "could not find billing"
            }

        # set new props
        billing['entity_id'] = billing_id
        try:
            billing['order_id'] = _req['order_id']
            billing['amount'] = _req['amount']
        except KeyError:
            return {
                "result": "missing mandatory parameter 'order_id' and/or 'amount"
            }

        res = self._check_amount(billing)
        if not res:
            return {
                'error': 'amount is not accurate'
            }

        # trigger event
        self.event_store.publish('billing', create_event('entity_updated', billing))

        return {
            "result": True
        }

    def delete_billing(self, _req):
        try:
            billing_id = _req['entity_id']
        except KeyError:
            return {
                "error": "missing mandatory parameter 'entity_id'"
            }

        rsp = send_message('read-model', 'get_entitiy', {'name': 'billing', 'id': billing_id})
        if 'error' in rsp:
            rsp['error'] += ' (from read-model)'
            return rsp

        billing = rsp['result']
        if not billing:
            return {
                "error": "could not find billing"
            }

        # trigger event
        self.event_store.publish('billing', create_event('entity_deleted', billing))

        return {
            "result": True
        }


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)-6s] %(message)s')

b = BillingService()

signal.signal(signal.SIGINT, lambda n, h: b.stop())
signal.signal(signal.SIGTERM, lambda n, h: b.stop())

b.start()
