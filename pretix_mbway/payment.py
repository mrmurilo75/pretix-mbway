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
    verbose_name = _('MBWay')
    payment_form_fields = OrderedDict([
    ])

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox('payment', 'mbway', event)

    @property
    def test_mode_message(self):
        if self.settings.environment == 'test':
            return _('The MB Way Plugin is being used in test mode')
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
                 label=_('MB WAY Key'),
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
