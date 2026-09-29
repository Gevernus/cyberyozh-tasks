import ipaddress

from django.http import Http404, HttpRequest, HttpResponse
from django_prometheus.exports import ExportToDjangoView

# Loopback and RFC 1918 / RFC 4193 ranges: where Docker networks and scrapers live.
INTERNAL_NETWORKS = [
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
]


def is_internal_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in network for network in INTERNAL_NETWORKS)


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Prometheus metrics for scrapers inside the private network.

    Judged by the socket address only: X-Forwarded-For is set by whoever sends the
    request. The reverse proxy is itself on the private network, so it must block
    this path too; see deploy/Caddyfile.
    """
    if not is_internal_address(request.META.get("REMOTE_ADDR", "")):
        raise Http404
    return ExportToDjangoView(request)
