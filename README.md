# Finance Tracker (Flask + SQLite)

This application provides:

- Monthly tracking of finances
- Multiple accounts per month (e.g., Bills Account, Joint Account, Personal Bills)
- Bills and incomes with optional owner/contributor fields
- User registration and login (Flask-Login)
- A grey-themed UI to mimic your spreadsheet’s style

## Setup
```sh
podman build --arch arm64 -t print-calc:latest .
sudo chcon -R -t svirt_sandbox_file_t ~/.local/share/containers/storage/volumes/finances-tracker-db/_data 
```

## Notes

- The configuration is in config.py.
- The app uses a local SQLite file (finance.db).
- Templates and static files are in the app/templates and app/static folders.
