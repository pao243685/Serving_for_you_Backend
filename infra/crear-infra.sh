#!/usr/bin/env bash
# =====================================================================
# Crea la infraestructura de Serving for you en AWS (Learner Lab) con la AWS CLI.
# Se ejecuta UNA vez desde la terminal del Learner Lab (ya trae credenciales):
#
#   curl -fsSL https://raw.githubusercontent.com/pao243685/Serving_for_you_Backend/develop/infra/crear-infra.sh | bash
#
# o, con una copia local del repo:   SRC_DIR=/ruta/al/repo bash infra/crear-infra.sh
#
# Crea (si no existen): sfy-front-sg, sfy-back-sg, IP elástica, bucket S3 de respaldos,
# EC2 B (backend + Postgres, sfy-back) y EC2 A (Caddy + front, sfy-front).
# Cada EC2 se configura sola al arrancar (user-data): Docker, /opt/sfy/.env con
# secretos generados en la propia instancia, cron de respaldos, fail2ban.
# Es repetible: lo que ya existe se reutiliza.
# =====================================================================
set -euo pipefail

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/pao243685/Serving_for_you_Backend/develop}"
REGION="${AWS_REGION:-$(aws configure get region || true)}"; REGION="${REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
KEY_NAME="${KEY_NAME:-vockey}"            # par de llaves que trae el Learner Lab
TYPE_FRONT="${TYPE_FRONT:-t3.small}"
TYPE_BACK="${TYPE_BACK:-t3.small}"
PROFILE="${PROFILE:-LabInstanceProfile}"
AZ="${AZ:-${REGION}a}"
# Dominios (DuckDNS) que apuntan a la IP elástica de la EC2 A. Vacíos = <IP>.sslip.io
DOMINIO_FRONT="${DOMINIO_FRONT:-serving-for-u.duckdns.org}"
DOMINIO_BACK="${DOMINIO_BACK:-serving-for-u-back.duckdns.org}"

log() { printf '\n\033[1;32m>> %s\033[0m\n' "$*"; }

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${BUCKET:-sfy-respaldos-${ACCOUNT}}"
log "Cuenta $ACCOUNT · región $REGION · zona $AZ"

aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null \
  || { echo "No existe el par de llaves $KEY_NAME"; exit 1; }

# ------------------------------------------------------------------ red
VPC="$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
SUBNET="$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=availability-zone,Values="$AZ" \
          Name=default-for-az,Values=true --query 'Subnets[0].SubnetId' --output text)"
log "VPC por defecto $VPC · subred $SUBNET"

sg_id() { aws ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC" Name=group-name,Values="$1" \
            --query 'SecurityGroups[0].GroupId' --output text; }
allow() { # allow SG PROTO PUERTO (cidr|sg) VALOR DESCRIPCION   (si la regla ya existe, no hace nada)
  local src
  if [ "$4" = cidr ]; then src="\"IpRanges\":[{\"CidrIp\":\"$5\",\"Description\":\"$6\"}]"
  else src="\"UserIdGroupPairs\":[{\"GroupId\":\"$5\",\"Description\":\"$6\"}]"; fi
  aws ec2 authorize-security-group-ingress --group-id "$1" \
    --ip-permissions "[{\"IpProtocol\":\"$2\",\"FromPort\":$3,\"ToPort\":$3,$src}]" >/dev/null 2>&1 || true
}

SG_FRONT="$(sg_id sfy-front-sg)"
if [ "$SG_FRONT" = None ]; then
  SG_FRONT="$(aws ec2 create-security-group --vpc-id "$VPC" --group-name sfy-front-sg \
    --description "Serving for you - EC2 A (Caddy + front): 80/443 publicos, 22 solo con llave" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=sfy-front-sg},{Key=Proyecto,Value=serving-for-you}]" \
    --query GroupId --output text)"
fi
allow "$SG_FRONT" tcp 80  cidr 0.0.0.0/0 "HTTP (Lets Encrypt y redireccion)"
allow "$SG_FRONT" tcp 443 cidr 0.0.0.0/0 "HTTPS del sitio"
allow "$SG_FRONT" tcp 22  cidr 0.0.0.0/0 "SSH solo con llave (runners de GitHub, IP variable) + fail2ban"

SG_BACK="$(sg_id sfy-back-sg)"
if [ "$SG_BACK" = None ]; then
  SG_BACK="$(aws ec2 create-security-group --vpc-id "$VPC" --group-name sfy-back-sg \
    --description "Serving for you - EC2 B (backend + BD): 8000 y 22 solo desde sfy-front-sg" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=sfy-back-sg},{Key=Proyecto,Value=serving-for-you}]" \
    --query GroupId --output text)"
fi
allow "$SG_BACK" tcp 8000 sg "$SG_FRONT" "API desde el Caddy del front"
allow "$SG_BACK" tcp 22   sg "$SG_FRONT" "SSH con salto por la EC2 del front"
log "Grupos de seguridad: sfy-front-sg=$SG_FRONT · sfy-back-sg=$SG_BACK"

# ------------------------------------------------------------------ IP elástica
ALLOC="$(aws ec2 describe-addresses --filters Name=tag:Name,Values=sfy-front-eip \
          --query 'Addresses[0].AllocationId' --output text)"
if [ "$ALLOC" = None ]; then
  ALLOC="$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=sfy-front-eip},{Key=Proyecto,Value=serving-for-you}]" \
    --query AllocationId --output text)"
fi
EIP="$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)"
SITE="${DOMINIO_FRONT:-${EIP}.sslip.io}"
ORIGINS="https://$SITE"
if [ -n "$DOMINIO_BACK" ]; then ORIGINS="$ORIGINS,https://$DOMINIO_BACK"; fi
log "IP elástica $EIP  ->  https://$SITE ${DOMINIO_BACK:+y https://$DOMINIO_BACK}"

# ------------------------------------------------------------------ S3 (respaldos)
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = us-east-1 ]; then
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
  '{"Rules":[{"ID":"borrar-respaldos-14-dias","Status":"Enabled","Filter":{"Prefix":"backups/"},"Expiration":{"Days":14}}]}' \
  || echo "(no se pudo crear la regla de ciclo de vida; no es grave)"
log "Bucket privado s3://$BUCKET"

# ------------------------------------------------------------------ AMI Ubuntu 24.04
AMI="$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
        --query Parameter.Value --output text 2>/dev/null || true)"
if [ -z "$AMI" ] || [ "$AMI" = None ]; then
  AMI="$(aws ec2 describe-images --owners 099720109477 \
    --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' Name=state,Values=available \
    --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)"
fi
log "AMI Ubuntu 24.04: $AMI"

instance_id() { aws ec2 describe-instances --filters Name=tag:Name,Values="$1" \
    Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[0].Instances[0].InstanceId' --output text; }

WORK="$(mktemp -d)"
if [ -n "${SRC_DIR:-}" ]; then
  cp "$SRC_DIR/infra/user-data-back.sh" "$WORK/back.sh"
  cp "$SRC_DIR/infra/user-data-front.sh" "$WORK/front.sh"
  cp "$SRC_DIR/deploy/setup-ec2.sh" "$WORK/setup-ec2.sh"
else
  curl -fsSL "$REPO_RAW/infra/user-data-back.sh"  -o "$WORK/back.sh"
  curl -fsSL "$REPO_RAW/infra/user-data-front.sh" -o "$WORK/front.sh"
  curl -fsSL "$REPO_RAW/deploy/setup-ec2.sh"      -o "$WORK/setup-ec2.sh"
fi
SETUP_B64="$(base64 -w0 "$WORK/setup-ec2.sh")"

# ------------------------------------------------------------------ EC2 B (backend + BD)
BACK="$(instance_id sfy-back)"
if [ "$BACK" = None ]; then
  sed -e "s|__ALLOWED_ORIGINS__|$ORIGINS|" -e "s|__S3_BUCKET__|$BUCKET|" -e "s|__SETUP_B64__|$SETUP_B64|" \
    "$WORK/back.sh" > "$WORK/back.final.sh"
  BACK="$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE_BACK" --key-name "$KEY_NAME" \
    --network-interfaces "DeviceIndex=0,SubnetId=$SUBNET,Groups=$SG_BACK,AssociatePublicIpAddress=true" \
    --iam-instance-profile Name="$PROFILE" \
    --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3,DeleteOnTermination=true}' \
    --user-data "file://$WORK/back.final.sh" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=sfy-back},{Key=Proyecto,Value=serving-for-you}]" \
                         "ResourceType=volume,Tags=[{Key=Name,Value=sfy-back},{Key=Proyecto,Value=serving-for-you}]" \
    --query 'Instances[0].InstanceId' --output text)"
  log "EC2 B creada: $BACK"
else
  log "EC2 B ya existía: $BACK"
fi
aws ec2 start-instances --instance-ids "$BACK" >/dev/null 2>&1 || true
aws ec2 wait instance-running --instance-ids "$BACK"
BACK_IP="$(aws ec2 describe-instances --instance-ids "$BACK" --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)"
log "IP privada de la EC2 B: $BACK_IP"

# ------------------------------------------------------------------ EC2 A (Caddy + front)
FRONT="$(instance_id sfy-front)"
if [ "$FRONT" = None ]; then
  sed -e "s|__BACKEND_UPSTREAM__|$BACK_IP:8000|" -e "s|__SITE_ADDRESS__|$SITE|" -e "s|__API_ADDRESS__|$DOMINIO_BACK|" -e "s|__SETUP_B64__|$SETUP_B64|" \
    "$WORK/front.sh" > "$WORK/front.final.sh"
  FRONT="$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE_FRONT" --key-name "$KEY_NAME" \
    --network-interfaces "DeviceIndex=0,SubnetId=$SUBNET,Groups=$SG_FRONT,AssociatePublicIpAddress=true" \
    --iam-instance-profile Name="$PROFILE" \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3,DeleteOnTermination=true}' \
    --user-data "file://$WORK/front.final.sh" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=sfy-front},{Key=Proyecto,Value=serving-for-you}]" \
                         "ResourceType=volume,Tags=[{Key=Name,Value=sfy-front},{Key=Proyecto,Value=serving-for-you}]" \
    --query 'Instances[0].InstanceId' --output text)"
  log "EC2 A creada: $FRONT"
else
  log "EC2 A ya existía: $FRONT"
fi
aws ec2 start-instances --instance-ids "$FRONT" >/dev/null 2>&1 || true
aws ec2 wait instance-running --instance-ids "$FRONT"
aws ec2 associate-address --allocation-id "$ALLOC" --instance-id "$FRONT" --allow-reassociation >/dev/null
log "IP elástica $EIP asociada a la EC2 A"

cat <<RES

=====================================================================
 LISTO. Las instancias terminan de configurarse solas en ~3-5 minutos.

 Sitio:               https://$SITE
 API:                 https://${DOMINIO_BACK:-$SITE/api}
 Los dominios DuckDNS deben apuntar a $EIP (duckdns.org).
 EC2 A (sfy-front):   $FRONT  · IP elástica $EIP
 EC2 B (sfy-back):    $BACK   · IP privada  $BACK_IP
 Bucket respaldos:    s3://$BUCKET

 Secretos de GitHub (repo backend → Settings → Secrets and variables → Actions):
   EC2_FRONT_HOST       = $EIP
   EC2_BACK_PRIVATE_IP  = $BACK_IP
   EC2_SSH_KEY          = contenido de labsuser.pem (AWS Details → Download PEM)
   DOCKERHUB_TOKEN      = token de Docker Hub      (secreto)
   DOCKERHUB_USERNAME   = usuario de Docker Hub    (VARIABLE, no secreto)
=====================================================================
RES
