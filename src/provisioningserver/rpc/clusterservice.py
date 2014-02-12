# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""RPC implementation for clusters."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "ClusterClientService",
    "ClusterService",
]

from itertools import starmap
import json
from operator import itemgetter
import random
from urlparse import urlparse

from apiclient.utils import ascii_url
from provisioningserver.cluster_config import get_maas_url
from provisioningserver.config import Config
from provisioningserver.pxe import tftppath
from provisioningserver.rpc import cluster
from twisted.application.internet import (
    StreamServerEndpointService,
    TimerService,
    )
from twisted.internet.address import HostnameAddress
from twisted.internet.endpoints import (
    connectProtocol,
    TCP4ClientEndpoint,
    TCP4ServerEndpoint,
    )
from twisted.internet.protocol import Factory
from twisted.protocols import amp
from twisted.python import log
from twisted.web.client import getPage


class Cluster(amp.AMP, object):
    """The RPC protocol supported by a cluster controller.

    This can be used on the client or server end of a connection; once a
    connection is established, AMP is symmetric.
    """

    @cluster.ListBootImages.responder
    def list_boot_images(self):
        images = tftppath.list_boot_images(
            Config.load_from_cache()['tftp']['root'])
        return {"images": images}


class ClusterService(StreamServerEndpointService):
    """A cluster controller RPC service.

    This is a service - in the Twisted sense - that exposes the
    ``Cluster`` protocol on the given port.
    """

    def __init__(self, reactor, port):
        super(ClusterService, self).__init__(
            TCP4ServerEndpoint(reactor, port),
            Factory.forProtocol(Cluster))


class ClusterClient(Cluster):
    """The RPC protocol supported by a cluster controller, client version.

    This works hand-in-hand with ``ClusterClientService``, maintaining
    the latter's `connections` map.

    :ivar address: The :class:`HostnameAddress` of the remote endpoint.

    :ivar service: A reference to the :class:`ClusterClientService` that
        made self.
    """

    address = None
    service = None

    def connectionMade(self):
        super(ClusterClient, self).connectionMade()
        if not self.service.running:
            self.transport.loseConnection()
        elif self.address in self.service.connections:
            self.transport.loseConnection()
        else:
            self.service.connections[self.address] = self

    def connectionLost(self, reason):
        if self.address in self.service.connections:
            if self.service.connections[self.address] is self:
                del self.service.connections[self.address]
        super(ClusterClient, self).connectionLost(reason)


class ClusterClientService(TimerService, object):
    """A cluster controller RPC client service.

    This is a service - in the Twisted sense - that connects to a set of
    remote AMP endpoints. The endpoints are obtained from a view in the
    region controller and periodically refreshed; this list is used to
    update the connections maintained in this service.

    :ivar connections: A mapping of endpoints to protocol instances
        connected to it.
    """

    def __init__(self, reactor):
        super(ClusterClientService, self).__init__(
            self._get_random_interval(), self.update)
        self.connections = {}
        self.clock = reactor

    def update(self):
        """Refresh outgoing connections.

        This obtains a list of endpoints from the region then connects
        to new ones and drops connections to those no longer used.
        """
        # 0. Update interval.
        self._update_interval()
        # 1. Obtain RPC endpoints.
        d = getPage(self._get_rpc_info_url())
        d.addCallback(json.loads)
        d.addCallback(itemgetter("endpoints"))
        # 2. Open connections to new endpoints.
        # 3. Close connections to defunct endpoints.
        d.addCallback(self._update_connections)
        # 4. Log errors.
        d.addErrback(log.err)
        return d

    @staticmethod
    def _get_rpc_info_url():
        """Return the URL to the RPC infomation page on the region."""
        url = urlparse(get_maas_url())
        url = url._replace(path="%s/rpc" % url.path.rstrip("/"))
        url = url.geturl()
        return ascii_url(url)

    @staticmethod
    def _get_random_interval():
        """Return a random interval between 30 and 90 seconds."""
        return random.randint(30, 90)

    def _update_interval(self):
        """Change the interval randomly to avoid stampedes of clusters."""
        self._loop.interval = self.step = self._get_random_interval()

    def _update_connections(self, hostports):
        connections_established = set(self.connections)
        connections_desired = set(starmap(HostnameAddress, hostports))
        self._make_connections(connections_desired - connections_established)
        self._drop_connections(connections_established - connections_desired)

    def _make_connections(self, addresses):
        for address in addresses:
            endpoint = TCP4ClientEndpoint(
                self.clock, address.hostname, address.port)
            protocol = ClusterClient()
            protocol.address = address
            protocol.service = self
            connectProtocol(endpoint, protocol)

    def _drop_connections(self, addresses):
        for address in addresses:
            self.connections[address].loseConnection()
