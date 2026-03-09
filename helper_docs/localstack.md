docker run -d `
   --name localstack `
   -p 4566:4566 `
   -e SERVICES=s3 `
   -e DEBUG=1 `
   -v /var/run/docker.sock:/var/run/docker.sock `
   localstack/localstack