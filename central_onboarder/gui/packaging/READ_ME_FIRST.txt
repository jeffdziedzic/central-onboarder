CENTRAL ONBOARDER - READ ME FIRST
=================================

Onboards new APs, switches, gateways and UXI sensors onto HPE GreenLake
(GLCP), New Central, Classic Central and the UXI application.

This is NOT an official HPE tool. It was built around one environment's
workflow. Use at your own risk, and try it on a test device first.


1. INSTALL
----------
1. Unzip this folder anywhere you like (Desktop, Documents...).
   Keep "Central Onboarder.exe" and the "_internal" folder together -
   the app needs both. There is no installer and no admin rights needed.
2. Double-click "Central Onboarder.exe".
3. Windows will probably warn you, because the app isn't code-signed:
     "Windows protected your PC"  ->  click "More info"  ->  "Run anyway"
   Your antivirus may also ask about it the first time.

Needs Windows 10 or 11 (it uses Microsoft Edge WebView2, which both
already include).


2. FIRST-TIME SETUP (Credentials screen)
----------------------------------------
1. Credentials -> Accounts: type a name for the customer (for example
   customer_ACME) and click Add.
2. "GreenLake Cloud Platform & New Central" card: enter the Base URL,
   Client ID and Client secret, then Save and Test. This one login is
   used for GreenLake, New Central and UXI.
   ("How do I get this?" on the card explains where to create it.)
3. Only if the customer still uses Classic Central: fill in the
   "Classic Central" card the same way (it also needs a Refresh token).
4. Only if you onboard UXI sensors: "UXI Application" card ->
   "Look up from GLCP..." and click the UXI entry.

Add one account per customer. The Account dropdown in the top bar picks
which customer every screen talks to - CHECK IT before running anything
that makes changes.


3. EVERYDAY USE
---------------
1. Device List: import a CSV (Download Template... shows the columns)
   or add devices by hand. Columns: Serial, MAC, Device Type
   (AP/Switch/Gateway/UXI), Target Group, Target Site, Subscription Key,
   Hostname.
2. Onboard Devices: Run Onboard Batch adds devices to GreenLake, assigns
   the subscription and service, and pre-provisions the group.
   Check Status looks up any serial or MAC.
3. Post Onboard (once devices have checked in): Assign Site, then
   Set Hostname.
4. Tools: Subscriptions shows which subscription keys have seats left.

The full User Guide opens from the Home screen.


4. YOUR FILES - KEEP THESE PRIVATE
----------------------------------
The app creates these next to the .exe:
  token.yaml        your API credentials for every customer. Treat it
                    like a password: never email it or put it in a
                    shared folder or zip.
  device-list.xlsx  your working device list (you can pick another file)
  workspace.json    remembers which device list you last used
  Command Outputs\  logs of every action and API call, for
                    troubleshooting

To share the app with someone else, give them the original zip - NOT
your own copy of this folder (it contains your token.yaml).


5. UPDATING TO A NEW VERSION
----------------------------
1. Close the app.
2. Unzip the new version into a NEW folder.
3. Copy token.yaml (and your device list, if it lives here) from the old
   folder into the new one.
4. Run the new .exe. Once it works, delete the old folder.


6. UNINSTALL
------------
Close the app and delete the folder. Nothing is installed elsewhere.
