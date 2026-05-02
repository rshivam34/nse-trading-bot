# Oracle Cloud + WireGuard — Free VPN Setup Guide

**Goal:** Get a free static IP that never changes, so you can run the trading bot from anywhere without updating Angel One's IP whitelist.

**Time required:** 60-90 minutes one-time setup. After that, zero maintenance.

**Cost:** ₹0 forever (Oracle Always Free tier).

---

## Before you start, you'll need

- A laptop with Windows
- A credit/debit card (for Oracle verification only — **not charged**)
- Your phone (for OTP)
- This document open beside you

---

# PHASE 1: Sign up for Oracle Cloud (15 min)

### Step 1.1 — Open the signup page

Go to **https://www.oracle.com/cloud/free/** in your browser.

You'll see a page with a button "**Start for free**" at the top right. Click it.

### Step 1.2 — Fill the signup form

You'll see a form asking for:

- **Country/Territory**: select **India**
- **Email**: use your real email (you'll need to verify it)
- **Click "Next"**

You'll get a verification email. Open your email, click the verification link, then return to the signup page.

### Step 1.3 — Account details

After email verification, fill:

- **Account Name**: anything, e.g., `shivam-trading-bot` (this is just a label)
- **Password**: create a strong password (save it somewhere safe — use the same password manager you use for trading credentials)
- **Country**: India
- **Click "Continue"**

### Step 1.4 — Address & phone

- Enter your address
- Enter your phone number — you'll get an OTP, enter it
- **Click "Continue"**

### Step 1.5 — Payment verification (NOT a charge)

Oracle verifies you're a real human by charging **₹0** but pre-authorizing your card. The actual amount taken is ₹0 — the pre-auth is released after a few days.

- Add a credit/debit card
- **Click "Start my free trial"** (don't worry, it's actually "Always Free" not just trial)

### Step 1.6 — Choose Home Region

**THIS IS IMPORTANT.** Oracle asks you to pick a "Home Region" which CANNOT be changed later.

Choose **India South (Hyderabad)** or **India West (Mumbai)** — whichever is closer to you. Lower latency = faster bot response.

If neither works (sometimes Oracle is full), pick **Singapore** as backup.

### Step 1.7 — Wait for account provisioning

After signup, Oracle takes 2-10 minutes to set up your account. You'll get a "Welcome" email when it's ready.

When you see the Oracle Cloud console (a dashboard with "Quick Actions" and "Resources" panels), you're in. **Bookmark this URL** — it's your control panel from now on.

---

# PHASE 2: Create the Always Free VM (15 min)

### Step 2.1 — Open the Compute > Instances page

In the Oracle Cloud Console:
- Click the **hamburger menu** (☰) at top-left
- Click **Compute** in the left sidebar
- Click **Instances**

You'll see "No instances found" — that's expected.

### Step 2.2 — Click "Create instance"

Big blue button at the top. Click it.

You'll see a page with multiple sections to fill.

### Step 2.3 — Name and Image

- **Name**: `nse-bot-vpn`
- **Image**: should already say "Canonical Ubuntu 22.04" — if not, click "Change image" and select Ubuntu 22.04

### Step 2.4 — Shape (CRITICAL — must select Ampere)

The default shape is a paid AMD shape. **You must change it to free Ampere ARM**.

- Click **"Change shape"**
- A dialog opens. Select **"Ampere"** in the left list
- Choose **"VM.Standard.A1.Flex"**
- Set **OCPUs to 1** and **Memory to 6 GB** (always free includes up to 4 OCPU / 24 GB total — start with 1/6 to leave room for other VMs later)
- Click **"Select shape"**

If you see the message "**Always Free Eligible**" badge — perfect.

> ⚠️ **If Oracle says "Out of capacity" for Ampere shapes:** This is common. Try again every few hours, or pick a different region (Singapore often has capacity). Some users have to retry for 1-2 days. Don't give up.

### Step 2.5 — Networking

- **Virtual cloud network**: leave default (Oracle creates one for you)
- **Subnet**: leave default
- **Public IPv4 address**: select **"Assign a public IPv4 address"** ← important

### Step 2.6 — SSH keys (CRITICAL)

This is how you'll log into the VM later.

- Select **"Generate a key pair for me"**
- **CLICK "Save Private Key" — DOWNLOAD this file** (it's a `.key` file, save somewhere safe like `C:\Users\rshiv\Documents\oracle-vm-key.key`)
- **CLICK "Save Public Key"** too (download)

> ⚠️ **You CAN NOT recover this key later.** If you lose it, you can't log into the VM. Save both files now.

### Step 2.7 — Boot volume

Leave defaults. The free tier includes 50 GB free.

### Step 2.8 — Click "Create"

The VM starts provisioning. Takes 1-3 minutes. You'll see "PROVISIONING" → "RUNNING" status.

### Step 2.9 — Note your VM's public IP

After "RUNNING", you'll see the VM details page. Find the **Public IPv4 address** — it looks like `129.213.45.123` or similar.

**Write this IP down.** This is what you'll whitelist at Angel One.

---

# PHASE 3: Reserve the IP (so it never changes) (5 min)

By default, Oracle gives you an "ephemeral" public IP — it changes if the VM restarts. We need a "reserved" IP that's permanent.

### Step 3.1 — Go to Public IPs

- Hamburger menu (☰) → **Networking** → **Public IPs**
- Click **"Reserve public IP address"**

### Step 3.2 — Reserve

- **Name**: `nse-bot-vpn-ip`
- **Compartment**: leave default (root compartment)
- Click **"Reserve public IP address"**

You'll see a new IP appear in the list, status "Available".

### Step 3.3 — Assign it to your VM

Hmm, actually the simpler approach: **convert your VM's existing ephemeral IP to reserved.**

- Go back to **Compute > Instances > nse-bot-vpn**
- Scroll down to "Attached VNICs" → click the VNIC name
- Find "Public IP Address" → click the **3-dot menu** next to it
- Select **"Edit"**
- Change **"Public IP Type"** from "Ephemeral" to "Reserved"
- Click "Update"

Now your VM's IP is permanent — won't change even if VM restarts.

---

# PHASE 4: Open WireGuard port in firewall (5 min)

By default, Oracle's firewall blocks everything except SSH. We need to allow WireGuard's port.

### Step 4.1 — Go to your VCN

- Hamburger menu (☰) → **Networking** → **Virtual Cloud Networks**
- Click your VCN (probably named like `vcn-XXX-XXX`)
- Click **"Security Lists"** in the left sidebar
- Click the **"Default Security List"**

### Step 4.2 — Add ingress rule

Click **"Add Ingress Rules"** button.

Fill in:
- **Stateless**: leave unchecked
- **Source Type**: CIDR
- **Source CIDR**: `0.0.0.0/0` (means any IP can connect to WireGuard — that's OK because we'll authenticate)
- **IP Protocol**: UDP
- **Destination Port Range**: `51820` (this is WireGuard's default port)
- **Description**: `WireGuard VPN`

Click **"Add Ingress Rules"**.

You should now see the new rule in the list.

---

# PHASE 5: SSH into the VM (10 min)

### Step 5.1 — Install Windows Terminal (if not already)

- Open Microsoft Store
- Search "**Windows Terminal**"
- Install it

(Alternatively, use built-in PowerShell or PuTTY.)

### Step 5.2 — Connect to the VM

Open Windows Terminal (or PowerShell). Type this command, replacing the path and IP:

```powershell
ssh -i "C:\Users\rshiv\Documents\oracle-vm-key.key" ubuntu@<YOUR_VM_PUBLIC_IP>
```

Example:
```powershell
ssh -i "C:\Users\rshiv\Documents\oracle-vm-key.key" ubuntu@129.213.45.123
```

If it asks "Are you sure you want to continue connecting (yes/no/[fingerprint])?", type **`yes`** and press Enter.

If you get a permission error like "Permissions on the private key file are too open", run this first:

```powershell
icacls "C:\Users\rshiv\Documents\oracle-vm-key.key" /inheritance:r /grant:r "%username%:R"
```

Then retry the SSH command.

### Step 5.3 — You're in!

You should now see a prompt like:
```
ubuntu@nse-bot-vpn:~$
```

Congratulations — you're inside your Oracle Cloud VM.

---

# PHASE 6: Install WireGuard (10 min)

### Step 6.1 — Update packages

In the SSH terminal, run:

```bash
sudo apt update && sudo apt upgrade -y
```

This takes 1-2 minutes.

### Step 6.2 — Run the WireGuard installer

Use the popular `wireguard-install.sh` script (open source, widely audited):

```bash
curl -O https://raw.githubusercontent.com/angristan/wireguard-install/master/wireguard-install.sh
chmod +x wireguard-install.sh
sudo ./wireguard-install.sh
```

The script asks several questions:

| Question | Answer |
|---|---|
| Public IPv4 or IPv6 address | Press Enter (auto-detected) |
| Public network interface | Press Enter (default `ens3`) |
| WireGuard port | Press Enter (`51820`) |
| First client name | Type `laptop` and press Enter |
| First DNS resolver | Press Enter (uses 1.1.1.1, fine) |

The script installs WireGuard, configures it, and creates a client file.

### Step 6.3 — Find the client config

The script prints a message like:
```
Your client configuration is in /home/ubuntu/wg0-client-laptop.conf
```

You need to copy this file to your Windows laptop.

### Step 6.4 — Download the config to your laptop

In your Windows Terminal, **open a NEW tab** (Ctrl+Shift+T) — keep the SSH session alive.

In the new tab, run:

```powershell
scp -i "C:\Users\rshiv\Documents\oracle-vm-key.key" ubuntu@<YOUR_VM_IP>:/home/ubuntu/wg0-client-laptop.conf C:\Users\rshiv\Documents\
```

This downloads `wg0-client-laptop.conf` to your `C:\Users\rshiv\Documents\` folder.

### Step 6.5 — Allow WireGuard port at OS level (just in case)

Back in your SSH session, run:

```bash
sudo ufw allow 51820/udp
sudo ufw status
```

---

# PHASE 7: Install WireGuard on your Windows laptop (5 min)

### Step 7.1 — Download WireGuard

- Go to **https://www.wireguard.com/install/**
- Click **"Download Windows Installer"**
- Run the installer

### Step 7.2 — Import your config

- Open WireGuard app on Windows
- Click **"Add Tunnel"** → **"Import tunnel(s) from file"**
- Browse to `C:\Users\rshiv\Documents\wg0-client-laptop.conf`
- Click "Open"

### Step 7.3 — Activate

- You'll see "wg0-client-laptop" in the WireGuard app
- Click **"Activate"**
- Status should change to "Active"

### Step 7.4 — Verify your IP changed

Open a browser and go to **https://whatismyipaddress.com**.

The IPv4 should now show your **Oracle VM's public IP** (e.g., `129.213.45.123`), NOT your Jio IP.

🎉 **Congratulations — your laptop now connects through Oracle Cloud's static IP.**

---

# PHASE 8: Update Angel One whitelist (2 min)

### Step 8.1 — Login to portal

Go to **https://smartapi.angelone.in/** and login.

### Step 8.2 — Update your app's IP

- Click **"My Apps"**
- Find **"NSE Trading Bot"**
- Click the **edit icon** (pencil)
- Change **Primary Static IP** from `49.32.238.63` to your **Oracle VM's IP** (e.g., `129.213.45.123`)
- Click **Save**

### Step 8.3 — Test

In your trading bot folder, run a quick auth test:

```powershell
cd C:\Users\rshiv\nse-trading-bot\backend
python -c "from config import config; from core.broker import BrokerConnection; b = BrokerConnection(config.broker, config.trading); print('Auth:', b.connect()); p = b.get_prev_day_ohlc('99926000', 'NIFTY'); print('Historical:', p)"
```

Expected output:
```
Auth: True
Historical: {'prev_open': ..., 'prev_high': ..., 'prev_low': ..., 'prev_close': ...}
```

If you see this, **everything works.** Your bot can now run from anywhere — home, office, mobile hotspot — as long as WireGuard is connected.

---

# DAILY USE

Once setup is done, your daily flow:

1. Open laptop
2. **Open WireGuard app, click Activate** (turns the VPN on)
3. Verify https://whatismyipaddress.com shows Oracle's IP
4. Double-click the bot's desktop launcher
5. Trade as usual

When you're done for the day, you can leave WireGuard active — it's lightweight.

If you reboot your laptop, just remember to activate WireGuard before starting the bot.

---

# MAINTENANCE (once every ~3 months)

Oracle requires the VM to be "active" or it might suspend it. Just SSH in once every 90 days:

```powershell
ssh -i "C:\Users\rshiv\Documents\oracle-vm-key.key" ubuntu@<YOUR_VM_IP>
sudo apt update && sudo apt upgrade -y
exit
```

That's the entire maintenance.

---

# TROUBLESHOOTING

### "Out of capacity" when creating VM

Oracle's Ampere is in high demand. Try:
- Different region (Singapore often has capacity)
- Try at different times of day (early morning IST often works)
- Wait 2-4 hours and retry

### Can't SSH

- Verify the IP is correct
- Verify you're using `ubuntu` as the username (not `root`)
- Verify the .key file path is correct
- Check Windows firewall isn't blocking SSH

### Bot still gets AG8004 after VPN setup

- Verify WireGuard is "Active" in the WireGuard app
- Check whatismyipaddress.com — you should see Oracle's IP
- Verify Angel One portal Primary IP matches Oracle's IP exactly
- Wait 5 minutes after Angel One save (sometimes their cache is slow)

### WireGuard suddenly disconnects

- Open WireGuard app, click "Activate" again
- If repeatedly disconnects, check Oracle VM is still RUNNING (sometimes Oracle pauses idle VMs)

### Oracle suspended my VM

If they email you saying VM was reclaimed for inactivity:
- Login to Oracle Cloud console
- Re-create the VM (same steps as Phase 2)
- The reserved IP is still yours — re-attach it
- Re-install WireGuard
- Update the laptop's `.conf` file

To prevent: SSH in monthly and run `sudo apt update`.

---

# COSTS — what you'll never be charged for

Oracle Always Free includes:
- 4 OCPUs Ampere ARM (you used 1)
- 24 GB RAM (you used 6)
- 200 GB block storage
- 10 TB outbound bandwidth/month
- 2 reserved public IPs (you used 1)
- 1 NAT gateway
- Free forever, no expiry

A bot trading session uses ~50 MB of bandwidth/day = ~1.5 GB/month. Well under the 10 TB limit.

---

# SUMMARY

Once this is set up, you have:
- ✅ Free static IP forever (no monthly cost)
- ✅ Trade from any network (home, office, mobile, café)
- ✅ Bot doesn't break when your local IP changes
- ✅ Single Angel One IP whitelist entry, never updated again

Estimated time investment: 60-90 min one-time, 5-10 min/quarter maintenance.

---

# IF YOU GET STUCK

Open a session with me and tell me which step. Common stuck points:
- Phase 1.5 (CC verification rejected) — try a different card or contact Oracle support
- Phase 2.4 (Ampere capacity) — wait or change region
- Phase 5.2 (SSH permission) — run the icacls command shown
- Phase 6 (WireGuard install fails) — paste the error, I'll diagnose

Good luck!
