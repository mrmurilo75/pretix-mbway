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
# This file contains Apache-licensed contributions copyrighted by: Flavia Bastos
#
# Unless required by applicable law or agreed to in writing, software distributed under the Apache License 2.0 is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under the License.

import json

import pretix_mbway.payment
import requests

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django_scopes import scopes_disabled

from pretix.base.models import Event, Order, OrderPayment, OrderRefund, Quota
from .models import MBWAYIfThenPayObject

from .ifthenpay import mbway

@csrf_exempt
@scopes_disabled()
def callback(request, *args, **kwargs):
    try:
        idpedido = request.GET['idpedido']
    except IndexError:
        return HttpResponse(405)

    mbw_order = mbway.get_order_by_id(idpedido)
    state = mbway.get_payment_state(
        mbway.require_state(
            mbw_order.mbway_key,
            mbw_order.channel,
            mbw_order.orderID
        )
    )

    if state == mbway.STATE_PAID:
        try:
            mbw_order.payment.confirm()
        except Quota.QuotaExceededException:
            pass
    elif state == mbway.STATE_CANCELLED:
        mbw_order.payment.fail()

    return HttpResponse(status=200)

