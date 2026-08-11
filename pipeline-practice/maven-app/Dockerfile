FROM registry.access.redhat.com/ubi8/openjdk-11:latest

WORKDIR /deployments
COPY target/catalog-app.jar /deployments/app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/deployments/app.jar"]
