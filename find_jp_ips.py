#!/usr/bin/env python3
import ipaddress
import random
import subprocess
import json
import time

def check_japan_ip(ip):
    """通过IP API验证是否在日本"""
    try:
        result = subprocess.run(
            f"curl -s -m 5 'http://ip-api.com/json/{ip}?fields=status,countryCode'",
            shell=True,
            capture_output=True,
            text=True
        )
        data = json.loads(result.stdout)
        return data.get('status') == 'success' and data.get('countryCode') == 'JP'
    except Exception as e:
        print(f"Error checking IP {ip}: {e}")
        return False

def main():
    # 读取CIDR文件
    with open("cf_all_cidr.txt") as f:
        cidrs = [line.strip() for line in f if line.strip()]

    print(f"Total CIDRs: {len(cidrs)}")

    # 限制网段数量，避免API限制
    jp_ips = []
    for cidr in cidrs[:20]:
        try:
            net = ipaddress.ip_network(cidr)
            samples_per_net = 25

            for _ in range(samples_per_net):
                random_offset = random.randint(1, min(net.num_addresses - 2, 1000))
                ip = str(net.network_address + random_offset)

                if check_japan_ip(ip):
                    print(f"Found Japan IP: {ip}")
                    jp_ips.append(ip)
                    with open("jp_ip_candidates.txt", "a") as out:
                        out.write(ip + "\n")

                time.sleep(0.5)

        except Exception as e:
            print(f"Error processing CIDR {cidr}: {e}")
            continue

    print(f"Total Japan IPs found: {len(jp_ips)}")

    with open("jp_ips.json", "w") as f:
        json.dump({
            "ips": jp_ips,
            "count": len(jp_ips),
            "timestamp": time.time()
        }, f, indent=2)

if __name__ == "__main__":
    main()
