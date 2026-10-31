# do PLEASE NOT install snap firefox, we dont like it, deb firefox better sar
cp -rf fucksnap /etc/apt/preferences.d/
install -d -m 0755 /etc/apt/keyrings
wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O- | tee /etc/apt/keyrings/packages.mozilla.org.asc > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" | tee -a /etc/apt/sources.list.d/mozilla.list > /dev/null
apt update

# now we install our beloved firefox without snap slop
apt install firefox -y
