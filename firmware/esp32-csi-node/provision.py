#!/usr/bin/env python3
"""
ESP32-S3 CSI Node Provisioning Script

Writes WiFi credentials and aggregator target to the ESP32's NVS partition
so users can configure a pre-built firmware binary without recompiling.

Usage:
    python provision.py --port COM7 --ssid "MyWiFi" --password "secret" --target-ip 192.168.1.20

    # Home WiFi: let the script discover the aggregator IP automatically
    python provision.py --port COM7 --ssid "HomeNetwork" --password "secret" --auto-discover

    # List available WiFi networks near the provisioning machine
    python provision.py --port COM7 --scan-networks

Requirements:
    pip install esptool nvs-partition-gen
    (or use the nvs_partition_gen.py bundled with ESP-IDF)
"""

import argparse
import csv
import io
import os
import socket
import struct
import subprocess
import sys
import tempfile


# NVS partition table offset — default for ESP-IDF 4MB flash with standard
# partition scheme.  The "nvs" partition starts at 0x9000 (36864) and is
# 0x6000 (24576) bytes.
NVS_PARTITION_OFFSET = 0x9000
NVS_PARTITION_SIZE = 0x6000  # 24 KiB

# UDP port the aggregator listens on for CSI frames (and discovery beacons).
AGGREGATOR_DEFAULT_PORT = 5005
# Discovery request sent as a UDP broadcast; aggregator replies with its IP.
DISCOVERY_REQUEST = b"RUVIEW_DISCOVER"
DISCOVERY_TIMEOUT = 2.0  # seconds


def get_local_ip():
    """Return the machine's primary outbound IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def scan_wifi_networks():
    """
    Return a list of visible WiFi networks as strings.

    Uses platform-specific commands (iwlist on Linux, netsh on Windows,
    airport on macOS).  Returns an empty list if scanning is unavailable.
    """
    networks = []
    try:
        if sys.platform.startswith("linux"):
            # Detect the active wireless interface from /proc/net/wireless
            iface = None
            try:
                with open("/proc/net/wireless") as f:
                    for line in f:
                        line = line.strip()
                        if ":" in line and not line.startswith("|"):
                            iface = line.split(":")[0].strip()
                            break
            except OSError:
                pass
            iface_arg = iface if iface else "wlan0"
            try:
                out = subprocess.check_output(
                    ["iwlist", iface_arg, "scanning"],
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                ).decode(errors="replace")
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("ESSID:"):
                        ssid = line.split(":", 1)[1].strip('"')
                        if ssid:
                            networks.append(ssid)
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
        elif sys.platform == "win32":
            out = subprocess.check_output(
                ["netsh", "wlan", "show", "networks"],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).decode(errors="replace")
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("SSID") and ":" in line:
                    parts = line.split(":", 1)
                    # Skip lines like "SSID Name" header
                    if parts[0].strip().upper() == "SSID":
                        ssid = parts[1].strip()
                        if ssid:
                            networks.append(ssid)
        elif sys.platform == "darwin":
            airport = (
                "/System/Library/PrivateFrameworks/Apple80211.framework"
                "/Versions/Current/Resources/airport"
            )
            if os.path.isfile(airport):
                out = subprocess.check_output(
                    [airport, "-s"],
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                ).decode(errors="replace")
                for line in out.splitlines()[1:]:  # skip header
                    parts = line.split()
                    if parts:
                        networks.append(parts[0])
    except Exception:
        pass
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for n in networks:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


def discover_aggregator(port=AGGREGATOR_DEFAULT_PORT, timeout=DISCOVERY_TIMEOUT):
    """
    Broadcast a discovery packet on the local network and wait for the
    aggregator to reply.  Returns the aggregator's IP string, or None.

    The aggregator (sensing-server) replies to RUVIEW_DISCOVER with its own
    IP:port so the provisioning script can obtain the target IP without the
    user having to look it up manually.
    """
    try:
        local_ip = get_local_ip()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.bind((local_ip, 0))
        sock.sendto(DISCOVERY_REQUEST, ("<broadcast>", port))
        try:
            data, (host, _) = sock.recvfrom(256)
            # Aggregator may reply with "RUVIEW_HERE:<ip>" or just an IP string.
            reply = data.decode(errors="replace").strip()
            if reply.startswith("RUVIEW_HERE:"):
                host = reply.split(":", 1)[1].strip()
            return host
        except socket.timeout:
            return None
        finally:
            sock.close()
    except Exception:
        return None


def build_nvs_csv(args):
    """Build an NVS CSV string for the csi_cfg namespace."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["key", "type", "encoding", "value"])
    writer.writerow(["csi_cfg", "namespace", "", ""])
    if args.ssid:
        writer.writerow(["ssid", "data", "string", args.ssid])
    if args.password is not None:
        writer.writerow(["password", "data", "string", args.password])
    if args.target_ip:
        writer.writerow(["target_ip", "data", "string", args.target_ip])
    if args.target_port is not None:
        writer.writerow(["target_port", "data", "u16", str(args.target_port)])
    if args.node_id is not None:
        writer.writerow(["node_id", "data", "u8", str(args.node_id)])
    # TDM mesh settings
    if args.tdm_slot is not None:
        writer.writerow(["tdm_slot", "data", "u8", str(args.tdm_slot)])
    if args.tdm_total is not None:
        writer.writerow(["tdm_nodes", "data", "u8", str(args.tdm_total)])
    # Edge intelligence settings (ADR-039)
    if args.edge_tier is not None:
        writer.writerow(["edge_tier", "data", "u8", str(args.edge_tier)])
    if args.pres_thresh is not None:
        writer.writerow(["pres_thresh", "data", "u16", str(args.pres_thresh)])
    if args.fall_thresh is not None:
        writer.writerow(["fall_thresh", "data", "u16", str(args.fall_thresh)])
    if args.vital_win is not None:
        writer.writerow(["vital_win", "data", "u16", str(args.vital_win)])
    if args.vital_int is not None:
        writer.writerow(["vital_int", "data", "u16", str(args.vital_int)])
    if args.subk_count is not None:
        writer.writerow(["subk_count", "data", "u8", str(args.subk_count)])
    # Home WiFi settings
    if args.enable_dhcp:
        writer.writerow(["dhcp_en", "data", "u8", "1"])
    if args.mdns_hostname:
        writer.writerow(["mdns_host", "data", "string", args.mdns_hostname])
    return buf.getvalue()


def generate_nvs_binary(csv_content, size):
    """Generate an NVS partition binary from CSV using nvs_partition_gen.py."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f_csv:
        f_csv.write(csv_content)
        csv_path = f_csv.name

    bin_path = csv_path.replace(".csv", ".bin")

    try:
        # Try the pip-installed version first (esp_idf_nvs_partition_gen package)
        try:
            from esp_idf_nvs_partition_gen import nvs_partition_gen
            nvs_partition_gen.generate(csv_path, bin_path, size)
            with open(bin_path, "rb") as f:
                return f.read()
        except ImportError:
            pass

        # Try legacy import name (older versions)
        try:
            import nvs_partition_gen
            nvs_partition_gen.generate(csv_path, bin_path, size)
            with open(bin_path, "rb") as f:
                return f.read()
        except ImportError:
            pass

        # Fall back to calling the ESP-IDF script directly
        idf_path = os.environ.get("IDF_PATH", "")
        gen_script = os.path.join(idf_path, "components", "nvs_flash",
                                  "nvs_partition_generator", "nvs_partition_gen.py")
        if os.path.isfile(gen_script):
            subprocess.check_call([
                sys.executable, gen_script, "generate",
                csv_path, bin_path, hex(size)
            ])
            with open(bin_path, "rb") as f:
                return f.read()

        # Last resort: try as a module
        subprocess.check_call([
            sys.executable, "-m", "nvs_partition_gen", "generate",
            csv_path, bin_path, hex(size)
        ])
        with open(bin_path, "rb") as f:
            return f.read()

    finally:
        for p in (csv_path, bin_path):
            if os.path.isfile(p):
                os.unlink(p)


def flash_nvs(port, baud, nvs_bin):
    """Flash the NVS partition binary to the ESP32."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(nvs_bin)
        bin_path = f.name

    try:
        cmd = [
            sys.executable, "-m", "esptool",
            "--chip", "esp32s3",
            "--port", port,
            "--baud", str(baud),
            "write_flash",
            hex(NVS_PARTITION_OFFSET), bin_path,
        ]
        print(f"Flashing NVS partition ({len(nvs_bin)} bytes) to {port}...")
        subprocess.check_call(cmd)
        print("NVS provisioning complete!")
    finally:
        os.unlink(bin_path)


def main():
    parser = argparse.ArgumentParser(
        description="Provision ESP32-S3 CSI Node with WiFi and aggregator settings",
        epilog=(
            "Examples:\n"
            "  python provision.py --port COM7 --ssid MyWiFi --password secret "
            "--target-ip 192.168.1.20\n"
            "  python provision.py --port COM7 --ssid HomeNetwork --password secret "
            "--auto-discover\n"
            "  python provision.py --port COM7 --scan-networks"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", required=True, help="Serial port (e.g. COM7, /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=460800, help="Flash baud rate (default: 460800)")
    parser.add_argument("--ssid", help="WiFi SSID")
    parser.add_argument("--password", help="WiFi password")
    parser.add_argument("--target-ip", help="Aggregator host IP (e.g. 192.168.1.20)")
    parser.add_argument("--target-port", type=int, help="Aggregator UDP port (default: 5005)")
    parser.add_argument("--node-id", type=int, help="Node ID 0-255 (default: 1)")
    # TDM mesh settings
    parser.add_argument("--tdm-slot", type=int, help="TDM slot index for this node (0-based)")
    parser.add_argument("--tdm-total", type=int, help="Total number of TDM nodes in mesh")
    # Edge intelligence settings (ADR-039)
    parser.add_argument("--edge-tier", type=int, choices=[0, 1, 2],
                        help="Edge processing tier: 0=off, 1=stats, 2=vitals")
    parser.add_argument("--pres-thresh", type=int, help="Presence detection threshold (default: 50)")
    parser.add_argument("--fall-thresh", type=int, help="Fall detection threshold (default: 500)")
    parser.add_argument("--vital-win", type=int, help="Phase history window in frames (default: 300)")
    parser.add_argument("--vital-int", type=int, help="Vitals packet interval in ms (default: 1000)")
    parser.add_argument("--subk-count", type=int, help="Top-K subcarrier count (default: 32)")
    # Home WiFi settings
    parser.add_argument(
        "--enable-dhcp", action="store_true",
        help="Enable DHCP on the ESP32 STA interface (default for home networks)",
    )
    parser.add_argument(
        "--mdns-hostname",
        help='mDNS hostname for this node (e.g. "ruview-1" → reachable as ruview-1.local)',
    )
    parser.add_argument(
        "--auto-discover", action="store_true",
        help=(
            "Broadcast a discovery packet on the local network to find the aggregator "
            "IP automatically. Useful on home networks where the aggregator IP changes. "
            "Falls back to --target-ip if discovery fails."
        ),
    )
    parser.add_argument(
        "--scan-networks", action="store_true",
        help="List visible WiFi networks and exit (helps finding the correct --ssid).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate NVS binary but don't flash")

    args = parser.parse_args()

    # --scan-networks: list nearby SSIDs and exit without flashing anything.
    if args.scan_networks:
        print("Scanning for visible WiFi networks...")
        networks = scan_wifi_networks()
        if networks:
            print(f"Found {len(networks)} network(s):")
            for n in networks:
                print(f"  • {n}")
        else:
            print(
                "No networks found (may require root/admin privileges or a WiFi-capable interface)."
            )
        return

    # --auto-discover: try to locate the aggregator on the LAN.
    if args.auto_discover and not args.target_ip:
        port = args.target_port or AGGREGATOR_DEFAULT_PORT
        print(f"Searching for aggregator on UDP broadcast port {port}...")
        discovered = discover_aggregator(port=port)
        if discovered:
            print(f"Aggregator found at {discovered}")
            args.target_ip = discovered
        else:
            local_ip = get_local_ip()
            print(
                f"Auto-discovery found no aggregator. "
                f"This machine's IP is {local_ip}. "
                f"Make sure the sensing server is running (--source esp32) and reachable on port {port}."
            )
            # Offer the machine's own IP as a fallback default.
            args.target_ip = local_ip
            print(f"Using local IP {local_ip} as fallback aggregator address.")

    has_value = any([
        args.ssid, args.password is not None, args.target_ip,
        args.target_port, args.node_id is not None,
        args.tdm_slot is not None, args.tdm_total is not None,
        args.edge_tier is not None, args.pres_thresh is not None,
        args.fall_thresh is not None, args.vital_win is not None,
        args.vital_int is not None, args.subk_count is not None,
        args.enable_dhcp, args.mdns_hostname is not None,
    ])
    if not has_value:
        parser.error("At least one config value must be specified")

    # Validate TDM: if one is given, both should be
    if (args.tdm_slot is not None) != (args.tdm_total is not None):
        parser.error("--tdm-slot and --tdm-total must be specified together")
    if args.tdm_slot is not None and args.tdm_slot >= args.tdm_total:
        parser.error(f"--tdm-slot ({args.tdm_slot}) must be less than --tdm-total ({args.tdm_total})")

    print("Building NVS configuration:")
    if args.ssid:
        print(f"  WiFi SSID:     {args.ssid}")
    if args.password is not None:
        print(f"  WiFi Password: {'*' * len(args.password)}")
    if args.target_ip:
        print(f"  Target IP:     {args.target_ip}")
    if args.target_port:
        print(f"  Target Port:   {args.target_port}")
    if args.node_id is not None:
        print(f"  Node ID:       {args.node_id}")
    if args.tdm_slot is not None:
        print(f"  TDM Slot:      {args.tdm_slot} of {args.tdm_total}")
    if args.edge_tier is not None:
        tier_desc = {0: "off (raw CSI)", 1: "stats", 2: "vitals"}
        print(f"  Edge Tier:     {args.edge_tier} ({tier_desc.get(args.edge_tier, '?')})")
    if args.pres_thresh is not None:
        print(f"  Pres Thresh:   {args.pres_thresh}")
    if args.fall_thresh is not None:
        print(f"  Fall Thresh:   {args.fall_thresh}")
    if args.vital_win is not None:
        print(f"  Vital Window:  {args.vital_win} frames")
    if args.vital_int is not None:
        print(f"  Vital Interval:{args.vital_int} ms")
    if args.subk_count is not None:
        print(f"  Top-K Subcarr: {args.subk_count}")
    if args.enable_dhcp:
        print("  DHCP:          enabled")
    if args.mdns_hostname:
        print(f"  mDNS hostname: {args.mdns_hostname}.local")

    csv_content = build_nvs_csv(args)

    try:
        nvs_bin = generate_nvs_binary(csv_content, NVS_PARTITION_SIZE)
    except Exception as e:
        print(f"\nError generating NVS binary: {e}", file=sys.stderr)
        print("\nFallback: save CSV and flash manually with ESP-IDF tools.", file=sys.stderr)
        fallback_path = "nvs_config.csv"
        with open(fallback_path, "w") as f:
            f.write(csv_content)
        print(f"Saved NVS CSV to {fallback_path}", file=sys.stderr)
        print(f"Flash with: python $IDF_PATH/components/nvs_flash/"
              f"nvs_partition_generator/nvs_partition_gen.py generate "
              f"{fallback_path} nvs.bin 0x6000", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        out = "nvs_provision.bin"
        with open(out, "wb") as f:
            f.write(nvs_bin)
        print(f"NVS binary saved to {out} ({len(nvs_bin)} bytes)")
        print(f"Flash manually: python -m esptool --chip esp32s3 --port {args.port} "
              f"write_flash 0x9000 {out}")
        return

    flash_nvs(args.port, args.baud, nvs_bin)


if __name__ == "__main__":
    main()
