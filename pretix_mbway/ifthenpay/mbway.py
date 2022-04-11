import requests
from .ifthenpayexception import IfThenPayException
from ..models import MBWAYIfThenPayObject

MBWAY_ENTRYPOINT = 'https://mbway.ifthenpay.com/IfthenPayMBW.asmx'
REQUIRE_PAYMENT_ENDPOINT = '/SetPedidoJSON'
REQUIRE_STATE_ENDPOINT = '/EstadoPedidosJSON'

STATE_PAID = '000'
STATE_CANCELLED = '020'
STATE_PENDING = '123'       # TODO it is also the state if user does not interact and it expires (there is no difference in pending and expired)

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

    request_accepted(result)  # raises exception if not accepted

    return result


def request_accepted(result):
    if result.status_code != 200:
        raise IfThenPayException('MBWay payment failed with status ' + result.status_code)
    elif result.json()['Estado'] != '000':
        raise IfThenPayException('MBWay payment failed with \'Estado\' ' + result.json()['Estado'])
    return True


payment_required = request_accepted


def create_order(result, mbwaykey, canal, payment):
    return MBWAYIfThenPayObject.objects.create(
        orderID=result.json().get('IdPedido'),
        mbway_key=mbwaykey,
        channel=canal,
        order=payment.order,
        payment=payment,
    )


def require_payment_state(mbwaykey, canal, idpedido):
    content = {
        'MbWayKey': mbwaykey,
        'Canal': canal,
        'idspagamento': idpedido,
    }

    result = requests.post(MBWAY_ENTRYPOINT + REQUIRE_STATE_ENDPOINT, headers=_content_type_header, data=content)
    print(result.json())

    if result.status_code == 200:
        res_json = result.json()
        if res_json['Estado'] == '000':
            return res_json['EstadoPedidos'][0]['Estado']

    return ''


def get_order_by_id(idpedido):
    return MBWAYIfThenPayObject.objects.get(orderID=idpedido)


def get_order_by_payment(payment):
    return MBWAYIfThenPayObject.objects.get(payment=payment)  # TODO test
