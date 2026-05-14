#!/usr/bin/env python3
"""Pause/enable Local Services Ads campaign on a schedule."""

import sys
from google.ads.googleads.client import GoogleAdsClient

CUSTOMER_ID = "5177347535"
MANAGER_ID = "3087463043"
DEV_TOKEN = "T6gwQMFjkJyV1-KT1hOFxg"
LSA_NAME = "LocalServicesCampaign:SystemGenerated:0005d4deb10e4ddf"


def load_secrets():
    s = {}
    with open("/root/.vikky_secrets") as f:
        for l in f:
            if "=" in l and not l.strip().startswith("#"):
                k, v = l.split("=", 1)
                s[k.strip()] = v.strip()
    return s


def get_client():
    s = load_secrets()
    return GoogleAdsClient.load_from_dict({
        "developer_token": DEV_TOKEN,
        "client_id": s["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": s["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": s["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": MANAGER_ID,
        "use_proto_plus": True,
    })


def find_lsa_campaign(client):
    ga = client.get_service("GoogleAdsService")
    query = (
        "SELECT campaign.id, campaign.name, campaign.status "
        "FROM campaign "
        "WHERE campaign.name = '" + LSA_NAME + "'"
    )
    rows = list(ga.search(customer_id=CUSTOMER_ID, query=query))
    if not rows:
        print(f"Campaign not found: {LSA_NAME}")
        sys.exit(1)
    row = rows[0]
    return row.campaign.id, row.campaign.name, row.campaign.status.name


def set_campaign_status(client, campaign_id, enable):
    campaign_service = client.get_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = campaign_service.campaign_path(CUSTOMER_ID, campaign_id)
    if enable:
        campaign.status = client.enums.CampaignStatusEnum.ENABLED
    else:
        campaign.status = client.enums.CampaignStatusEnum.PAUSED
    client.copy_from(
        operation.update_mask,
        client.get_type("FieldMask")(paths=["status"]),
    )
    campaign_service.mutate_campaigns(
        customer_id=CUSTOMER_ID, operations=[operation]
    )


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("on", "off", "status"):
        print("Usage: lsa_scheduler.py [on|off|status]")
        sys.exit(1)

    cmd = sys.argv[1]
    client = get_client()
    cid, name, status = find_lsa_campaign(client)

    if cmd == "status":
        print(f"{name} | {status} | campaign_id={cid}")
        return

    if cmd == "off":
        if status == "PAUSED":
            print(f"Already paused: {name}")
        else:
            set_campaign_status(client, cid, enable=False)
            print(f"PAUSED: {name}")

    if cmd == "on":
        if status == "ENABLED":
            print(f"Already enabled: {name}")
        else:
            set_campaign_status(client, cid, enable=True)
            print(f"ENABLED: {name}")


if __name__ == "__main__":
    main()
