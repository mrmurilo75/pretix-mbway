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
import decimal
import json
import requests
import logging
import urllib.parse
from collections import OrderedDict
from decimal import Decimal
from typing import Any, Dict, Union

from django import forms
from django.contrib import messages
from django.core import signing
from django.http import HttpRequest
from django.template.loader import get_template
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext as __, gettext_lazy as _
from i18nfield.strings import LazyI18nString

from pretix.base.decimal import round_decimal
from pretix.base.models import Event, Order, OrderPayment, OrderRefund, Quota
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.settings import SettingsSandbox
from pretix.helpers.urls import build_absolute_uri as build_global_uri
from pretix.multidomain.urlreverse import build_absolute_uri

logger = logging.getLogger('pretix.plugins.mbway')

SUPPORTED_CURRENCIES = ['EUR']


class MBWAY(BasePaymentProvider):
    identifier = 'mbway'
    verbose_name = _('MBWAY')
    payment_form_fields = OrderedDict([
    ])

    _mbway_api = 'https://mbway.ifthenpay.com/IfthenPayMBW.asmx'
    _payment_type = 'ifthenpaymbway'

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox('payment', 'mbway', event)

    @property
    def test_mode_message(self):
        if self.settings.environment == 'test':
            return _('The MBWAY Plugin is being used in test mode')
        return None

    @property
    def settings_form_fields(self):
        fields = [
            ('mbway_key',
             forms.CharField(
                 label=_('MBWAY Key'),
                 required=True,
                 help_text=_('<a target="_blank" rel="noopener" href="{docs_url}">{text}</a>').format(
                     text=_('Click here for more information'),
                     docs_url='https://helpdesk.ifthenpay.com/en/support/home'
                 )
             )),
            ('channel',
             forms.CharField(
                 label=_('Channel'),
                 required=False,
                 help_text=_('<a target="_blank" rel="noopener" href="{docs_url}">{text}</a>').format(
                     text=_('Click here for more information'),
                     docs_url='https://helpdesk.ifthenpay.com/en/support/home'
                 )
             )),
        ]

        extra_fields = [
            ('description',
             forms.CharField(
                 label=_('Reference description'),
                 help_text=_('Any value entered here will be added to the call'),
                 required=False,
             )),
        ]

        d = OrderedDict(
            fields + extra_fields + list(super().settings_form_fields.items())
        )

        d.move_to_end('description')
        d.move_to_end('_enabled', False)
        return d

    def is_allowed(self, request: HttpRequest, total: Decimal = None) -> bool:
        return super().is_allowed(request, total) and self.event.currency in SUPPORTED_CURRENCIES

    def payment_is_valid_session(self, request):
        return True

    def payment_form_render(self, request) -> str:
        template = get_template('pretix_mbway/checkout_payment_form.html')
        ctx = {}
        return template.render(ctx)

    def checkout_prepare(self, request, cart):
        return request.session.get('telemovel', '') != ''

    def checkout_confirm_render(self, request: HttpRequest, order: Order) -> str:
        if self.settings.get('environment') == 'gateway':
            template = get_template('pretix_mbway/checkout_payment_confirm_gateway.html')
            ctx = {}
            return template.render(ctx)

        template = get_template('pretix_mbway/checkout_payment_confirm.html')
        ctx = {'telemovel': request.session.get('telemovel', ''),
               'referencia': self.settings.get('description', ''),
               'amount': order.total,
              }
        return template.render(ctx)


    def _format_price(self, value: float):
        return f'{value: .2f}'

    def execute_payment(self, request: HttpRequest, payment: OrderPayment) -> str:
        telemovel = request.session.get('telemovel', '')
        if telemovel == '':
            payment.state = payment.PAYMENT_STATE_FAILED
            raise PaymentException(_(f'Something went wrong with the payment processing [ { request.status_code } ] : Phone number not in session'))

        amount = self._format_price(payment.amount)
        referencia = self.settings.get('description', '')

        method = 'POST'
        api_url = self._mbway_api + '/SetPedidoJSON'
        header = {
            'Content-type' : 'application/x-www-form-urlencoded',
        }
        content = {
            'MbWayKey'   : self.settings.get('mbway_key', ''),
            'Canal'      : self.settings.get('channel', ''),
            'Referencia' : self.settings.get('description', ''),
            'valor'      : amount,
            'nrtlm'      : telemovel,
            'email'      : '',
            'descricao'  : self.settings.get('description', ''),
        }

        result = requests.request(method, api_url, headers=header, data=content)
        if result.status_code == '200':
            obj, created = MBWAYIfThenPayObject.objects.get_or_create(
                orderID   = result_json.get('IdPedido'),
                mbway_key = self.settings.get('mbway_key', ''),
                channel   = self.settings.get('channel', ''),
                order     = payment.order,
                payment   = payment,
            )
            obj.save()
            payment['IdPedido'] = result_json.get('IdPedido')
            payment.state = payment.PAYMENT_STATE_PENDING
            payment.save()
            return None

        payment.state = payment.PAYMENT_STATE_FAILED
        raise PaymentException(f'Something went wrong with the payment processing [ { result.status_code } ] : { result.text }')

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
        return '{% load i18n %} <p>IfThenPay Payment ID : ' + str(payment['IdPedido']) + '</p>'

    def payment_control_render_short(self, payment: OrderPayment) -> str:
        return f'{ self.get_order_id(payment) }: { payment.state }'

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return False

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return False

    def api_payment_details(self, payment: OrderPayment):
        return {
            'order_id': payment['IdPedido'],
            'description': self.settings.get('description', ''),
            'amount': payment.amount,
            'status': payment.status,
        }

    def matching_id(self, payment: OrderPayment):
        return payment['IdPedido']

