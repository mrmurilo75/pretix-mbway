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
            ('ifthenpay_gateway_key',
             forms.CharField(
                 label=_('IfThenPay Gateway Key'),
                 required=True,
                 help_text=_('<a target="_blank" rel="noopener" href="{docs_url}">{text}</a>').format(
                     text=_('Click here for more information'),
                     docs_url='https://helpdesk.ifthenpay.com/en/support/solutions/articles/79000128524-api-generate-paybylink-url'
                 )
             )),
            ('mb_way_key',
             forms.CharField(
                 label=_('MBWAY Key'),
                 required=True,
                 help_text=_('<a target="_blank" rel="noopener" href="{docs_url}">{text}</a>').format(
                     text=_('Click here for more information'),
                     docs_url='https://helpdesk.ifthenpay.com/en/support/solutions/articles/79000128524-api-generate-paybylink-url'
                 )
             )),
            ('environment',
             forms.ChoiceField(
                 label=_('Environment'),
                 initial='live',
                 choices=(
                     ('live', 'Live'),
                     ('test', 'Test'),
                 ),
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
        return True

    def checkout_confirm_render(self, request) -> str:
        template = get_template('pretix_mbway/checkout_payment_confirm.html')
        ctx = {}
        return template.render(ctx)

    def get_order_id(self, payment: OrderPayment) -> str:
        if not payment.info:
            payment.info = '{}'
        old = json.loads(payment.info)
        try:
            old['order_id']
        except KeyError:
            old['order_id'] = f'{payment.local_id % (10 ** 15) : 04d}'
            payment.info = json.dumps(old)
            payment.save(update_fields=['info'])
        return old['order_id']

    def _format_price(self, value: float):
        return f'{value: .2f}'

    def get_expire_date(self, payment: OrderPayment):
        if not payment.info:
            payment.info = '{}'
        old = json.loads(payment.info)
        try:
            old['expire_date']
        except KeyError:
            today = now()
            old['expire_date'] = f'{today.year}{today.month}{today.day}'
            payment.info = json.dumps(old)
            payment.save(update_fields=['info'])
        return old['expire_date']

    def execute_payment(self, request: HttpRequest, payment: OrderPayment) -> str:
        key_gateway = self.settings.get('ifthenpay_gateway_key', '')
        id_order = self.get_order_id(payment)
        amount = self._format_price(payment.amount)
        description = self.settings.get('description', '')
        language = request.headers.get('locale', 'en')
        key_mbway = self.settings.get('mb_way_key', '')
        expire_date = self.get_expire_date(payment)

        if key_gateway == '' or id_order == '' or amount == '' or key_mbway == '':
            logger.exception('IfThenPay Invalid Credentials')
            raise PaymentException(_('IfThenPay Invalid credentials'))

        api_url = f"https://ifthenpay.com/api/gateway/paybylink/get?gatewaykey={ key_gateway }&id={ id_order }&amount={ amount }&description={ description }&lang={ language }&expiredate={ expire_date }&accounts=MBWAY|{ key_mbway }"

        ifthenpay_result = requests.get(api_url)

        if ifthenpay_result.status_code == '200':
            payment.state = payment.PAYMENT_STATE_PENDING
            payment.save()
            return self.ifthenpay_result
        raise PaymentException('Something went wrong with the payment processing')

    def calculate_fee(self, price: Decimal) -> Decimal:
        return 0;

    def payment_pending_render(self, request, payment) -> str:
        template = get_template('pretix_mbway/pending.html')
        ctx = {}
        return template.render(ctx)

    @property
    def abort_pending_allowed(self) -> bool:
        return False

    # def render_invoice_text(self, order: Order, payment: OrderPayment) -> str:

    def order_change_allowed(self, order: Order) -> bool:
        return False

    def payment_prepare(self, request: HttpRequest, payment: OrderPayment) -> Union[bool, str]:
        return True

    def payment_control_render(self, request: HttpRequest, payment: OrderPayment):
        template = get_template('pretix_mbway/control.html')

        id_order = self.get_order_id(payment)
        amount = self._format_price(payment.amount)
        description = self.settings.get('description', '')
        language = request.headers.get('locale', 'en')
        expire_date = self.get_expire_date(payment)
        status = payment.state

        ctx = {'id_order': id_order, 'amount': amount, 'description': description, 'language': language, 'expire_date': expire_date, 'status': status}
        return template.render(ctx)

    def payment_control_render_short(self, payment: OrderPayment) -> str:
        return f'{ self.get_order_id(payment) }: { payment.state }'

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return False

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return False

    def api_payment_details(self, payment: OrderPayment):
        return {
            'id_order': self.get_order_id(payment),
            'description': self.settings.get('description', ''),
            'amount': payment.amount,
            'status': payment.status,
        }

    def matching_id(self, payment: OrderPayment):
        return self.get_order_id(payment)

    def shred_payment_info(self, obj: Union[OrderPayment, OrderRefund]):
        if obj.info:
            new = {}
            order_id = obj.info_data.get('order_id', '')
            if order_id != '':
                new['order_id'] = order_id
            expire_date = obj.info_data.get('expire_date', '')
            if expire_date != '':
                new['expire_date'] = expire_date
            obj.info_data = new
            obj.save(update_fields=['info'])

    # def cancel_payment(self, payment: OrderPayment):

