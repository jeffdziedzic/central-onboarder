# Central Onboarder - User Guide

This is not an official tool. It was built around a single environment's
onboarding workflow by an amateur coder. Use at your own risk.

## Status

v0.1.0 is a fresh scaffold. Nothing in this tool has been exercised
against a real GLCP/New Central/Classic Central tenant yet - every API
call it makes was ported from a sibling project (the AOS8-to-AOS10
Conversion Tool) where the endpoint/body shape WAS live-confirmed, but
that confirmation doesn't carry over automatically to this tool's own
first real run. Treat every screen as unverified until you've clicked
it against a real tenant and it did what you expected. In particular:

- "Assign Service" (application assignment) auto-discovers Central's
  application ID from another already-assigned device in your
  workspace - this only works if your workspace already has at least
  one device assigned to Central. A brand-new/empty workspace needs an
  explicit application ID (the manual card's optional Application ID
  field). UXI's application ID has no auto-discovery at all yet (see
  below) - it must be entered in Credentials before Run Onboard Batch
  can assign UXI rows their service.
- Site assignment goes through Classic Central's site-association API
  even for New-Central-managed devices, mirroring what the sibling
  conversion project found actually works live. If your tenant is
  fully migrated off Classic Central, this may need revisiting.
- "Look up from GLCP..." (Credentials screen's UXI Application card)
  calls HPE's documented Service Catalog API (GET service-catalog/v1/
  service-managers) to list provisioned service instances by name/id -
  confirmed to exist and documented, but NOT yet confirmed that its
  `id` is the same application_id restore_central_assignment reads/
  writes on a device record. A wrong guess here just means the looked-
  up ID doesn't work when you try to assign it - verify on first live
  use.
- UXI support is new and entirely unverified against a real tenant -
  in particular, whether GLCP's "assign application" call actually
  behaves the same way for the UXI application as it does for Central
  is assumed, not confirmed.

## Assumptions and limitations

- Onboards APs, switches, gateways, and UXI sensors. UXI sensors skip
  pre-provisioning and New Central site assignment entirely - those
  are Central-only concepts, since UXI sensors sit in GLCP under their
  own UXI application, not Central.
- UXI does NOT have its own separate credential - it reuses the same
  New Central/GLCP client (client_credentials grant) as everything
  else. The only UXI-specific thing you store is its application_id
  (and region, if applicable), on the Credentials screen - not a
  secret, just an identifier GLCP needs to know which application to
  attach a device to.
- A Windows .exe build exists (see `gui/packaging/README_windows.md`);
  macOS packaging hasn't been built yet.
- No CLI - the GUI is the only front end.

## Before you start

- **Credentials**: this tool needs a New Central API client
  (client_credentials grant - also used for GLCP and UXI calls, no
  separate GLCP credential needed) and, for group pre-provisioning and
  site assignment, a Classic Central API client (refresh_token grant).
  UXI rows additionally need a UXI application_id stored (see the
  Credentials screen's UXI Application card). See the Credentials
  screen's "How do I get this?" links for the OAuth clients.
- **Accounts / token.yaml**: credentials live in `token.yaml` next to
  the app (next to the .exe in the Windows build), in the same format
  as the aruba_central project's token.yaml, so an account block can be
  copied between the two files. One account = one customer/tenant:

  ```yaml
  accounts:
    customer_ACME:
      base_url: https://us4.api.central.arubanetworks.com   # New Central / GLCP
      client_id: ...
      client_secret: ...
      apigw_base_url: https://apigw-uswest4.central.arubanetworks.com  # Classic Central (optional)
      apigw_client_id: ...
      apigw_client_secret: ...
      apigw_refresh_token: ...
      uxi_application_id: ...   # optional, this tool only
  default: customer_ACME
  ```

  The **Account** dropdown in the top bar (visible on every screen) picks which account every
  screen talks to (it's saved as `default`). Double-check it before
  running anything that makes changes. You can edit the file by hand or
  through the Credentials screen; when the app saves it, any comments
  you added are dropped. The Classic refresh token changes every time
  it's used and the app writes the new one back, so don't keep a
  second copy of the same Classic login in another tool's file. An
  older `credentials.json` is imported into `token.yaml` automatically
  on first launch and can be deleted afterwards.
- **Device list**: a single working Excel file tracks every device
  you're onboarding - its columns are Serial, MAC, Device Type (AP /
  Switch / Gateway / UXI), Target Group, Target Site, Subscription Key,
  Hostname, plus tracking columns this tool fills in as you complete
  each step. Leave Target Group/Target Site/Hostname blank on UXI rows.
  A device list made by an older version (no Hostname column) is
  upgraded automatically the first time it's opened - existing data
  moves with it. Import a CSV or add
  devices manually from the Device List screen - a CSV can freely mix
  all four device types in one file.

## Screens

1. **Credentials** - add or delete accounts, and store the selected
   account's New Central and Classic Central API clients, UXI
   application_id, and an (unused) AP SSH credential. Test checks a
   credential without writing anything; Test All checks every account.
2. **Device List** - set your working device-list file, import a CSV,
   or add/edit devices manually.
3. **Onboard Devices** - Run Onboard Batch: for pending devices, add to GLCP,
   assign a subscription, assign the service (Central for AP/Switch/
   Gateway rows, UXI's application for UXI rows), and pre-provision
   AP/Switch/Gateway rows with a Target Group to a Classic Central
   group - all in one pass. Each of the Manual cards below it (Add to
   GLCP, Assign Service/Remove, Assign Subscription/Remove,
   Pre-Provision) does one of those steps alone: type/paste an explicit
   list of serials/MACs (plus a group, key, or application ID as that
   card needs) to act on devices you name directly, or check "Pull from
   Device List" to instead run that one step against the whole sheet -
   same as a slice of Run Onboard Batch, useful for retrying just one
   step. Check Status looks up a serial or MAC's full state across both
   GLCP/New Central and Classic Central in one go.
4. **Post Onboard** - manual steps you run when you know devices are
   online, not an automatic background poll. This tool assumes New
   Central is used for configuration.
   - **Assign Site**: once an AP/Switch/Gateway device has actually
     checked into Central, assign it to a New Central site. Type an
     explicit list of serials, or check "Pull from Device List" to
     instead assign every eligible sheet row to its own Target Site.
     "Pull Sites" fetches site names from Classic Central into a
     dropdown.
   - **Set Hostname**: sets the device's hostname in New Central, in
     its own copy of the default System Information profile
     (`sys-system-info-profile`, same for APs, switches and gateways).
     The device must already be provisioned in New Central (in a site
     or device group) - an unprovisioned device is reported and
     skipped, nothing is written. Type serials and hostnames paired in
     order, or check "Pull from Device List" to set every row with a
     Hostname not yet marked "Host." (UXI rows skipped).
     Tick **Set in Classic Central** for customers still configuring in
     Classic Central. The device must have checked into Classic Central.
     APs are renamed through Classic's AP settings, switches through
     their `_sys_hostname` variable, and gateways with a device-level `hostname` command in their
     group. **UI groups only**: a device in a Classic template group
     is refused without changing anything (its hostname belongs to
     the customer's template). Tested on AOS10 UI-group APs and
     gateways and an AOS-CX switch.
   - **Create New Site**.
5. **Tools**
   - **Reset to Default** (clears the working device list pointer and
     every stored credential).
   - **Subscriptions**: Pull Subscriptions lists the selected
     account's GreenLake subscriptions - key, category (Advanced AP,
     Foundation Switch...), type, available/total, end date, Eval.
     Expired and fully used ones are hidden unless you tick the boxes;
     Category and Type have filter dropdowns. Handy for picking a
     Subscription Key for the device list. Read-only.
