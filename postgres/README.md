flyctl proxy <local port>:5432 -a potholes-db.
then you can use localhost:<local port> with the db credentials to connect from your machine.
Other fly machines in our space can access the DB without issue.
