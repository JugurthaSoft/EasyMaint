# EasyMaint — free CMMS for industrial SMEs

**English** | [Français](README.fr.md)

*"The functional power of a professional CMMS, with the ease of use of a modern application."*

**Version 1.1.0** · free software under the **AGPL-3.0** license · © 2026 Jamil KHALFALLAH and contributors · a [JugurthaSoft](https://jugurthasoft.com) product

Source code: https://github.com/jugurthasoft/easymaint · Contact: contact@jugurthasoft.com

A web application in French or English (language chosen at installation), built with Django, HTMX, Bootstrap 5
and PostgreSQL, and delivered as Docker containers. The same code runs on a server inside the plant, with no
Internet access, or as a multi-company online service (SaaS).

## Features

- **Assets**: location tree, equipment and sub-assemblies, technical data, documents, meters, QR codes, PDF equipment sheet.
- **Maintenance work**: work requests, corrective and improvement work orders, assignment, mobile technician screen (timer, checklist, report), production stoppages, validation, frozen costs, PDF work order sheet, Excel export.
- **Preventive**: calendar and meter-based plans, automatic work order generation, postponement, schedule, completion rate.
- **Condition monitoring**: measurement points, versioned thresholds (vibration, oil, temperature…), trend charts, alerts, trigger rules, CSV/Excel import, sensor API.
- **Stores**: items, stores, suppliers, weighted average cost, reservation and issue to work orders with signed issue and return slips, stock counts, bills of materials, printable purchase requests, restocking suggestions.
- **Costs and budget**: analysis by equipment, unit, family, maintenance type and month; annual budget per unit; Excel and PDF reports.
- **KPIs**: MTBF, MTTR, availability, corrective rate, backlog… with their definitions; automatic monthly PDF report; home page customisable by each user.
- **Commissioning**: Excel imports (equipment, items with initial stock, suppliers, maintenance history), with French or English column headers.
- **Security and operations**: 8 roles and 29 editable permissions, activity log, data isolated per company, lockout after failed logins, in-app notifications, nightly automatic backups.

## Quick installation

On Windows (with Docker Desktop installed), from the EasyMaint folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Demo
```

On Linux (with Docker installed):

```bash
sh scripts/install.sh --demo
```

Then open `http://<server-address>:8000`. Without `-Demo` / `--demo`, only your own company is created.
The script asks for the installation language (French or English); the demo data is loaded in that language.

## Documentation

The detailed guides are currently in French; English versions will follow.

- [Installation and operation](docs/installation.md): local installation, backup and restore, updates, troubleshooting
- [Online deployment (SaaS)](docs/deploiement-cloud.md): rented server, automatic HTTPS, one address per company
- [User guide](docs/utilisation.md)
- [Architecture](docs/architecture.md): multi-company rules, permissions, coding conventions
- [Changelog](docs/CHANGELOG.md)
- API: `/api/v1/` (browsable once logged in). For a sensor or another application: `docker compose exec web python manage.py create_api_token <username>`, then the header `Authorization: Token <token>`; measurements are sent to `/api/v1/mesures/` (see the user guide).

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
sh scripts/vendor_static.sh          # Bootstrap, HTMX, Chart.js served locally
python manage.py migrate             # SQLite by default in development
python manage.py load_demo --password "Demo-EasyMaint-2026"
python manage.py runserver
```

### Tests

```bash
pytest                                          # locally
docker compose run --rm web pytest              # in the container (EASYMAINT_REQUIREMENTS=dev in .env)
```

The test suite covers in particular: data isolation between companies (database, forms, API, files, QR codes),
role permissions on every page, document numbering, meter rules, the audit log, the consistency between models
and migrations, and the completeness of the English translation.

## Contributing

Contributions are welcome (fixes, translations, new features): see [CONTRIBUTING.md](CONTRIBUTING.md).

## License and services

EasyMaint is free software: you can use, study, modify and redistribute it under the terms of the
[GNU Affero General Public License version 3](LICENSE) (see also [COPYRIGHT](COPYRIGHT)).
If you offer a modified version to users over a network (online service), you must give them access to its
source code (`EASYMAINT_SOURCE_URL`, shown on the "About" page).

The author offers installation, commissioning (data migration, configuration), team training, hosting and
custom development: contact@jugurthasoft.com.
