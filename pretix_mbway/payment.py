#
# This file is part of pretix (Community Edition).
#
# Copyright (C) 2014-2020 Raphael Michel and contributors
# Copyright (C) 2020-2021 rami.io GmbH and contributors
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General
# Public License as published by the Free Software Foundation in version 3 of the License.
#
# ADDITIONAL TERMS APPLY: Pursuant to Section 7 of the GNU Affero General Public License, additional terms are
# applicable granting you additional permissions and placing additional restrictions on your usage of this software.
# Please refer to the pretix LICENSE file to obtain the full terms applicable to this work. If you did not receive
# this file, see <https://pretix.eu/about/en/license>.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License along with this program.  If not, see
# <https://www.gnu.org/licenses/>.
#

# This file is based on an earlier version of pretix which was released under the Apache License 2.0. The full text of
# the Apache License 2.0 can be obtained at <http://www.apache.org/licenses/LICENSE-2.0>.
#
# This file may have since been changed and any changes are released under the terms of AGPLv3 as described above. A
# full history of changes and contributors is available at <https://github.com/pretix/pretix>.
#
# This file contains Apache-licensed contributions copyrighted by: Jakob Schnell, Tobias Kunze
#
# Unless required by applicable law or agreed to in writing, software distributed under the Apache License 2.0 is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under the License.
import json
import logging
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from typing import Union

import requests
from django import forms
from django.contrib import messages
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.translation import gettext_lazy as _
from pretix.base.models import Event, Order, OrderPayment
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.settings import SettingsSandbox

from .models import MBWAYGatewayObject

logger = logging.getLogger('pretix.plugins.mbway')

SUPPORTED_CURRENCIES = ['EUR']

_sibs_api_endpoint = 'https://spg.qly.site1.sibs.pt/'
_sibs_api_local = 'api/v1/payments'


class MBWAY(BasePaymentProvider):
    identifier = 'mbway'
    verbose_name = _('MBWAY')

    _spg_documentation = 'https://www.pay.sibs.com/documentacao/sibs-gateway/'
    _sibs_api_market = 'https://developer.sibsapimarket.com/sandbox/node/3085'

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox('payment', self.identifier, event)

    @property
    def settings_form_fields(self) -> dict:
        fields = [
            ('terminal_id',
             forms.IntegerField(
                 label=_('Terminal Id'),
                 required=True,
                 help_text=_(f'<p>Obtained on SIBS BackOffice, or provided by your bank</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
                 max_value=10 ** 6,
             )),
            ('client_id',
             forms.CharField(
                 label=_('X-IBM-Client-Id'),
                 required=True,
                 help_text=_(f'<p>Obtained on SIBS BackOffice, or provided Onboarding</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
             )),
            ('access_token',
             forms.CharField(
                 label=_('Bearer / Access Token'),
                 required=True,
                 help_text=_(f'<p>Obtained on SIBS BackOffice</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
             )),
            ('payment_type',
             forms.ChoiceField(
                 label=_('Payment Type'),
                 required=True,
                 initial='AUTH',
                 choices=(
                     ('AUTH', _('For one time transactions - AUTH')),
                     ('PURS', _('For two time transactions - PURS')),
                 ),
                 help_text=_(f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
             )),
            ('payment_entity',
             forms.CharField(
                 label=_('Payment Entity'),
                 required=True,
                 help_text=_(f'<p>Obtained on SIBS BackOffice, or provided by your bank</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
             )),
            ('payment_method',
             forms.CharField(
                 label=_('Payment Method'),
                 required=False,
                 help_text=_(f'<p>Selected when you sign the contract with the Bank</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
             )),
            ('merchant_id',
             forms.CharField(
                 label=_('Merchant Id'),
                 required=True,
                 help_text=_(f'<p>Unique id used by the merchant</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._sibs_api_market}">'
                             f'SIBS API Market</a></p>'
                             ),
             )),

            # ('mb_way',
            #  forms.BooleanField(
            #      label=_('MB Way'),
            #      required=False,
            #      help_text=_(f'<p>Allow MB Way payment on Forms Integration</p>\n'
            #                  f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
            #                  f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
            #                  ),
            #  )),
            # ('mb_reference',
            #  forms.BooleanField(
            #      label=_('MB Reference'),
            #      required=False,
            #      help_text=_(f'<p>Allow MB Reference payment on Forms Integration</p>\n'
            #                  f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
            #                  f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
            #                  ),
            #  )),
        ]

        extra_fields = [
            ('description',
             forms.CharField(
                 label=_('Description'),
                 required=True,
                 help_text=_(f'<p>Arbitrary text to be added as transaction description in payment</p>\n'
                             f'<p>For more info check <a target="_blank" href="{self._spg_documentation}">'
                             f'SIBS PAYMENT GATEWAY - Getting Started</a></p>'
                             ),
             )),
        ]

        d = OrderedDict(
            fields + extra_fields + list(super().settings_form_fields.items())
        )
        d.move_to_end('_enabled', False)

        return d

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return True

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return True

    @property
    def payment_form_fields(self) -> dict:
        fields = [
            ('telemovel',
             forms.IntegerField(
                 label=_('Telemovel'),
                 required=True,
                 max_value=10 ** 10,
             )),
        ]

        d = OrderedDict(
            fields
        )

        return d

    def is_allowed(self, request: HttpRequest, total: Decimal = None) -> bool:
        return super().is_allowed(request, total) and self.event.currency in SUPPORTED_CURRENCIES

    def payment_is_valid_session(self, request):
        return True

    def checkout_prepare(self, request, cart):
        try:
            telemovel = request.POST.get('payment_mbway-telemovel')
        except KeyError:
            messages.error(request, 'Invalid request: Missing phone number')
            return False
        request.session['telemovel'] = telemovel
        return request.session.get('telemovel', '') != ''

    def checkout_confirm_render(self, request, order: Order = None) -> str:
        template = get_template('pretix_mbway/checkout_payment_confirm.html')
        ctx = {'telemovel': request.session.get('telemovel', ''),
               'referencia': self.settings.get('description', ''),
               }
        return template.render(ctx)

    def execute_payment(self, request: HttpRequest, payment: OrderPayment) -> str:
        telemovel = request.session.get('telemovel', '')
        if telemovel == '':
            payment.state = payment.PAYMENT_STATE_FAILED
            raise PaymentException(
                _(f'Something went wrong with the payment processing [ {request.status_code} ] : Phone number not in session'))

        timestamp = datetime.now()

        payment_methods = ['MBWAY']
        amount = {
            'value': float(payment.amount),
            'currency': 'EUR'
        }
        merchant = {
            'terminalId': self.settings.get('terminal_id', 00000, int),
            'channel': 'web',
            'merchantTransactionId': self.settings.get('merchant_id', 'SPG_DEFAULT_PRETIX'),
        }
        payment_reference = {
            'initialDatetime': f'{timestamp.isoformat()}Z',
            'finalDatetime': f'{datetime.fromtimestamp(timestamp.timestamp() + 24 * 3600).isoformat()}Z',  # 1 day
            'maxAmount': amount,
            'minAmount': amount,
            'entity': self.settings.get('payment_entity', '24000')
        }
        transaction = {
            'transactionTimestamp': timestamp.isoformat() + 'Z',
            'description': self.settings.get('description', 'Pretix SIBS Payment Gateway'),
            'moto': False,
            'paymentType': self.settings.get('payment_type', 'AUTH'),
            'amount': amount,
            'paymentMethod': payment_methods,
            'paymentReference': payment_reference,
        }

        data = json.dumps({
            'merchant': merchant,
            'transaction': transaction,
        }).replace("'", '"')
        headers = {
            'Authorization': 'Bearer {}'.format(self.settings.get('access_token', '')),
            'X-IBM-Client-Id': self.settings.get('client_id', ''),
            'Content-Type': 'application/json'
        }

        checkout_sts = requests.post(_sibs_api_endpoint + _sibs_api_local, data=data, headers=headers)
        checkout_sts = checkout_sts.json()

        return_status = checkout_sts['returnStatus']
        if return_status['statusCode'] != '000':
            payment.state = payment.PAYMENT_STATE_FAILED
            payment.save()
            raise PaymentException(
                _(f'Something went wrong with the payment processing [ {return_status["statusCode"]} ] : {return_status["statusMessage"]}'))

        # TODO MAKE ATOMIC
        data = json.dumps({
            'customerPhone': f'351#{telemovel}'
        })
        headers = {
            'Authorization': f'Digest {checkout_sts["transactionSignature"]}',
            'X-IBM-Client-Id': self.settings.get('client_id', ''),
            'Content-Type': 'application/json'
        }
        print(headers)
        print(data)

        transaction_sts = requests.post(
            f'{_sibs_api_endpoint}{_sibs_api_local}/{checkout_sts["transactionID"]}/mbway-id/purchase',
            data=data, headers=headers).json()
        print(transaction_sts)

        return_status = transaction_sts['returnStatus']
        if return_status['statusCode'] != '000':
            payment.state = payment.PAYMENT_STATE_FAILED
            payment.save()
            raise PaymentException(
                _(f'Something went wrong with the payment processing [ {return_status["statusCode"]} ] : {return_status["statusMessage"]}'))

        MBWAYGatewayObject.objects.create(
            transactionID=checkout_sts["transactionID"],
            order=payment.order,
            payment=payment,
        )
        payment.state = payment.PAYMENT_STATE_PENDING
        payment.save()
        return None

    def payment_pending_render(self, request, payment) -> str:
        template = get_template('pretix_mbway/pending.html')
        ctx = {}
        return template.render(ctx)

    @property
    def abort_pending_allowed(self) -> bool:
        return False

    def order_change_allowed(self, order: Order) -> bool:
        return False

    def payment_prepare(self, request: HttpRequest, payment: OrderPayment) -> Union[bool, str]:
        return request.session.get('telemovel', '') != ''

    def payment_control_render(self, request: HttpRequest, payment: OrderPayment):
        print(MBWAYGatewayObject.objects.get(payment=payment).transactionID)
        return f'<p>Transaction ID: {MBWAYGatewayObject.objects.get(payment=payment).transactionID} </p>'

    def payment_control_render_short(self, payment: OrderPayment) -> str:
        return f'{MBWAYGatewayObject.objects.get(payment=payment).transactionID} : {payment.state}'

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return True

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return True

    def api_payment_details(self, payment: OrderPayment):
        return {
            'transaction_id': MBWAYGatewayObject.objects.get(payment=payment).transactionID,
            'amount': payment.amount,
            'status': payment.status,
        }

    def matching_id(self, payment: OrderPayment):
        return MBWAYGatewayObject.objects.get(payment=payment).transactionID
