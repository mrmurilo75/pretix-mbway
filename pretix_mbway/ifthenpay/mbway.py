import requests

MBWAY_ENTRYPOINT = 'https://mbway.ifthenpay.com/IfthenPayMBW.asmx'
REQUIRE_PAYMENT_ENDPOINT = '/SetPedidoJSON'
REQUIRE_STATE_ENDPOINT = '/EstadoPedidosJSON'

STATE_PAID = '000'
STATE_CANCELLED = '123'

_content_type_header = {
        'Content-type': 'application/x-www-form-urlencoded',
    }

def require_payment(mbwaykey, canal, referencia, descricao, valor, telemovel, email=''):
    content = {
        'MbWayKey': mbwaykey,
        'Canal': canal,
        'Referencia': referencia,
        'valor': valor,
        'nrtlm': telemovel,
        'email': email,
        'descricao': descricao,
    }
    result = requests.post(MBWAY_ENTRYPOINT + REQUIRE_PAYMENT_ENDPOINT, headers=_content_type_header, data=content)

    # TODO if !request_accepted(result): raise exception

    return result

def request_accepted(result):
    return result.status_code == 200 and result.json()['Estado'] == '000'

payment_required = request_accepted

def create_order(result, mbwaykey, canal, payment):
    created, obj = MBWAYIfThenPayObject.objects.get_or_create(
                orderID   = result.json().get('IdPedido'),
                mbway_key = mbwaykey,
                channel   = canal,
                order     = payment.order,
                payment   = payment,
            )

    # TODO
    #  if !created: raise exception

    return obj

def get_payment_state(result):
    return result.json()['EstadoPedidos'][0]['Estado']

def require_state(mbwaykey, canal, idpedido):
    content = {
        'MbWayKey': mbwaykey,
        'Canal': canal,
        'idspagamento': idpedido,
    }

    return requests.post(api_url, headers=_content_type_header, data=content)

def get_order_by_id(idpedido):
    return MBWAYIfThenPayObject.objects.get(orderID=idpedido)

def get_order_by_payment(payment):
    return MBWAYIfThenPayObject.objects.get(payment=payment)    # TODO test
