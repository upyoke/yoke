# Temporary self-hosted server fixture

Use this when a QA case needs a real self-hosted Yoke server (for example the
self-hosted target of an acceptance criterion). It starts one small EC2
instance, installs the current published release, serves it over HTTPS, runs
the cases from an isolated machine home, and tears everything down again.

The fixture creates exactly two cloud resources: one instance (with its root
volume) and one security group. Everything else is what the documented
[self-host install](../self-host.md) creates on that instance.

## Rules

- Run every AWS call through `yoke aws exec --project yoke -- <aws args>`. It
  uses the project's AWS capability; never paste or print its credentials.
- Never print the server's admin token or database secrets. Pipe the token
  straight from the server into `yoke connect --token-stdin`.
- **Connect only from an isolated machine home.** Set
  `YOKE_MACHINE_HOME=<scratch dir>` for every command that targets the
  fixture. Your real `~/.yoke/config.json` maps checkouts to project ids
  without saying which connection they belong to. A fresh self-hosted
  universe also starts at project id 1, so if you connect the fixture there,
  its ids collide with your production mappings and the claim-refusal cases
  name the wrong folder.
- Tag both resources with an owner and an expiry, and give the instance a
  shutdown timer, so a missed teardown still cleans itself up.

## Setup

Work in a scratch directory, for example `/tmp/yoke-selfhost-qa`. Keep the
ids it writes (`sg`, `instance`, `pubip`); teardown needs them.

```bash
cd /tmp/yoke-selfhost-qa
A(){ yoke aws exec --project yoke -- "$@"; }   # zsh: a function, not a variable
ssh-keygen -q -t ed25519 -N '' -C yoke-selfhost-qa -f key
curl -fsS https://checkip.amazonaws.com > myip
A ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text > ami
TAGS='{Key=Name,Value=yoke-selfhost-qa},{Key=Project,Value=yoke},{Key=Purpose,Value=self-host-qa-fixture},{Key=Owner,Value=NAME},{Key=Item,Value=PREFIX-N},{Key=Expires,Value=YYYY-MM-DDTHH:MMZ}'
VPC=$(A ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
A ec2 create-security-group --group-name yoke-selfhost-qa --description "Temporary Yoke self-host QA fixture" \
  --vpc-id $VPC --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" --query GroupId --output text > sg
A ec2 authorize-security-group-ingress --group-id $(cat sg) --ip-permissions \
  "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$(cat myip)/32}]" \
  "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=$(cat myip)/32}]" \
  "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=acme-http-01}]"
```

Port 80 is open to everyone only so Let's Encrypt can issue the certificate;
SSH and HTTPS are open only to your address.

Write `user-data.sh`. It installs Docker and Caddy, adds your public key, and
powers the instance off after 12 hours. Because the shutdown behavior below is
`terminate`, powering off deletes the instance:

```bash
#!/bin/bash
set -euo pipefail
shutdown -h +720 "yoke self-host QA fixture expiry"
install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
echo 'PASTE key.pub HERE' >> /home/ubuntu/.ssh/authorized_keys
chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys; chmod 0600 /home/ubuntu/.ssh/authorized_keys
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git docker.io docker-compose-v2 caddy
systemctl enable --now docker; usermod -aG docker ubuntu
touch /var/lib/cloud/instance/yoke-fixture-ready
```

Start the instance (t3.small is enough) and wait for it:

```bash
A ec2 run-instances --image-id $(cat ami) --instance-type t3.small --security-group-ids $(cat sg) \
  --instance-initiated-shutdown-behavior terminate --metadata-options HttpTokens=required \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3,DeleteOnTermination=true}' \
  --user-data file://user-data.sh \
  --tag-specifications "ResourceType=instance,Tags=[$TAGS]" "ResourceType=volume,Tags=[$TAGS]" \
  --query 'Instances[0].InstanceId' --output text > instance
A ec2 wait instance-running --instance-ids $(cat instance)
A ec2 describe-instances --instance-ids $(cat instance) \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text > pubip
echo "$(tr . - < pubip).sslip.io" > host
```

Run remote steps through one small helper, `s.sh`, which feeds its standard
input to the instance as a shell script. Passing commands on stdin also keeps
remote paths out of local command lines, where the session hooks would read
them as local folders:

```bash
#!/bin/sh
D=/tmp/yoke-selfhost-qa
exec ssh -i $D/key -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$D/known_hosts \
  -o BatchMode=yes ubuntu@$(cat $D/pubip) bash -s
```

Wait until `test -f /var/lib/cloud/instance/yoke-fixture-ready` succeeds.
Then install the release and start the server:

```bash
./s.sh <<'EOF'
set -e
curl -fsSL https://upyoke.com/install | sh
export PATH="$HOME/.local/bin:$PATH"
yoke version
yoke self-host init --admin-name "NAME" --start
EOF
```

Put HTTPS in front of the server. Caddy obtains the certificate for the
`sslip.io` name. The trusted proxy is the Docker network gateway, so the
server accepts the forwarded client address:

```bash
./s.sh <<EOF
set -e
export PATH="\$HOME/.local/bin:\$PATH"
printf '%s {\n\treverse_proxy 127.0.0.1:8765\n}\n' '$(cat host)' | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl reload caddy
sed -i 's/^YOKE_API_TRUSTED_PROXIES=.*/YOKE_API_TRUSTED_PROXIES=172.18.0.1/' ~/yoke-server/.env
yoke self-host init --dir ~/yoke-server --protect-existing --start
EOF
curl -fsS https://$(cat host)/v1/health
```

If the gateway differs, read it with
`docker network inspect yoke-server_default --format '{{(index .IPAM.Config 0).Gateway}}'`.

## Run cases

Connect from a scratch machine home. The token goes straight from the server
into `yoke connect` and is never printed:

```bash
mkdir -m 700 engineer-home
export YOKE_MACHINE_HOME=/tmp/yoke-selfhost-qa/engineer-home YOKE_ENV=selfhost-ec2-qa
echo 'cat ~/yoke-server/secrets/first-boot-admin-token' | ./s.sh \
  | yoke connect https://$(cat host) --name selfhost-ec2-qa --token-stdin
```

Run each QA case's command with those two variables set, and keep its logs as
evidence. To start again from an empty universe:

```bash
./s.sh <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
yoke self-host teardown --dir ~/yoke-server --destroy-universe --yes
yoke self-host init --dir ~/yoke-server --protect-existing --start
EOF
```

After a reset, delete and recreate the scratch home before connecting again.

## Teardown

```bash
A ec2 terminate-instances --instance-ids $(cat instance)
A ec2 wait instance-terminated --instance-ids $(cat instance)
A ec2 delete-security-group --group-id $(cat sg)
rm -rf /tmp/yoke-selfhost-qa
```

Check that nothing tagged `Purpose=self-host-qa-fixture` is left:
`A ec2 describe-instances --filters Name=tag:Purpose,Values=self-host-qa-fixture
Name=instance-state-name,Values=pending,running,stopping,stopped` and
`A ec2 describe-security-groups --filters Name=tag:Purpose,Values=self-host-qa-fixture`
must both come back empty. The shutdown timer deletes the instance but not the
security group, so delete the group yourself even when the timer has fired.
