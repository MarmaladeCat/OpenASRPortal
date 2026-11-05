"""Generate a local self-signed TLS certificate with explicit DNS/IP SANs."""

import argparse
import ipaddress
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", required=True, help="DNS name or IP; repeatable")
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / "runtime/tls"
    )
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    sans = []
    for host in args.host:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            if len(host) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                for part in host.split(".")
            ):
                parser.error("--host must be a DNS name or IP address, without a scheme or port")
            sans.append(x509.DNSName(host))
    if not 1 <= args.days <= 3650:
        parser.error("--days must be between 1 and 3650")
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / name).exists() for name in ("server.key", "server.crt")):
        parser.error("certificate already exists; generate in a new directory for rotation")
    with tempfile.TemporaryDirectory(dir=args.output) as directory:
        key, cert = Path(directory) / "server.key", Path(directory) / "server.crt"
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, args.host[0][:64])])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=args.days))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private.public_key()), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(private.public_key()),
                critical=False,
            )
            .sign(private, hashes.SHA256())
        )
        key.write_bytes(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        os.chmod(key, 0o600)
        os.chmod(cert, 0o644)
        key.replace(args.output / key.name)
        cert.replace(args.output / cert.name)
    print(f"Certificate created in {args.output}; trust server.crt on each client.")


if __name__ == "__main__":
    main()
