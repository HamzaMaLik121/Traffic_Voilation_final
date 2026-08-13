AWS_REGION=us-east-1
AWS_ACCOUNT_ID=839706991042
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_TAG="20260812-2307"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker tag traffic-worker:latest \
  "$ECR_REGISTRY/traffic-violation/worker:$IMAGE_TAG"
docker tag traffic-api:latest \
  "$ECR_REGISTRY/traffic-violation/api:$IMAGE_TAG"
docker tag traffic-dashboard:latest \
  "$ECR_REGISTRY/traffic-violation/dashboard:$IMAGE_TAG"

docker tag traffic-worker:latest \
  "$ECR_REGISTRY/traffic-violation/worker:latest"
docker tag traffic-api:latest \
  "$ECR_REGISTRY/traffic-violation/api:latest"
docker tag traffic-dashboard:latest \
  "$ECR_REGISTRY/traffic-violation/dashboard:latest"

docker push "$ECR_REGISTRY/traffic-violation/worker:$IMAGE_TAG"
docker push "$ECR_REGISTRY/traffic-violation/api:$IMAGE_TAG"
docker push "$ECR_REGISTRY/traffic-violation/dashboard:$IMAGE_TAG"

docker push "$ECR_REGISTRY/traffic-violation/worker:latest"
docker push "$ECR_REGISTRY/traffic-violation/api:latest"
docker push "$ECR_REGISTRY/traffic-violation/dashboard:latest"
