import requests

URL = "https://zip.cm.edu.kg/all.txt"
TARGET_COUNTRIES = {"JP", "US", "SG", "DE"}

def main():
    print("Downloading data...")
    resp = requests.get(URL, timeout=60)
    resp.raise_for_status()

    lines = resp.text.splitlines()

    result = {c: [] for c in TARGET_COUNTRIES}

    for line in lines:
        line = line.strip()
        if not line or "#" not in line:
            continue

        try:
            ip_port, country = line.split("#", 1)
        except ValueError:
            continue

        country = country.strip().upper()

        if country in TARGET_COUNTRIES:
            result[country].append(f"{ip_port}#{country}")

    for country, items in result.items():
        filename = f"{country.lower()}.txt"
        print(f"Writing {filename} ({len(items)} lines)")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(items) + "\n")

    print("Done.")

if __name__ == "__main__":
    main()
