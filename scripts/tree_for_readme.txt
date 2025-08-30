Mode            Length Hierarchy
----            ------ ---------
d----        219.61 KB Anwill_Back_Catalog
-a---         393.00 B     ├── gunicorn.conf.py
-a---          1.52 KB     ├── .env.example
-a---         81.89 KB     ├── package-lock.json
-a---          1.27 KB     ├── Dockerfile
-a---          2.06 KB     ├── .env
-a---         435.00 B     ├── .dockerignore
-a---         23.64 KB     ├── Makefile
-a---         49.84 KB     ├── README.md
-a---         10.21 KB     ├── CHANGELOG.md
-a---         34.37 KB     ├── .env.lang
-a---          32.00 B     ├── version.txt
-a---         264.00 B     ├── package.json
-a---          1.80 KB     ├── pyproject.toml
-a---          1.13 KB     ├── alembic.ini
-a---          7.18 KB     ├── run.py
-a---          3.42 KB     ├── .gitignore
-a---         195.00 B     ├── .gitmessage.txt
-a---           0.00 B     ├── __init__.py
d----         15.38 KB     scripts
-a---         874.00 B         ├── notify_telegram.py
-a---         694.00 B         ├── version.py
-a---         793.00 B         ├── add_dep.py
-a---          1.58 KB         ├── generate_changelog_git_changelog.py
-a---         11.20 KB         ├── tree_for_readme.txt
-a---         307.00 B         ├── update_version.py
-a---           0.00 B         ├── __init__.py
d----          8.67 KB         tools
-a---          1.90 KB             ├── gen_tree.py
-a---          3.15 KB             ├── num_code.py
-a---          3.62 KB             ├── dev_secret_gen.py
-a---           0.00 B             ├── __init__.py
d----           0.00 B     app
-a---           0.00 B         ├── __init__.py
d----           0.00 B         frontend
d----         24.58 KB             templates
-a---         12.29 KB                 ├── swagger_login_catalog.html
-a---         12.29 KB                 ├── swagger_login_platform.html
d----          1.65 KB             static
-a---          1.65 KB                 ├── main.js
d----         33.45 KB         services
-a---         33.45 KB             ├── jobs_with_file.py
-a---           0.00 B             ├── __init__.py
d----         577.00 B             celery
-a---         192.00 B                 ├── tasks.py
-a---         385.00 B                 ├── __init__.py
d----          3.05 KB             cache
-a---          3.05 KB                 ├── obj_cache.py
-a---           0.00 B                 ├── __init__.py
d----         12.54 KB             s3
-a---         11.08 KB                 ├── tasks.py
-a---          1.46 KB                 ├── __init__.py
d----         416.00 B             taskiq
-a---         212.00 B                 ├── tasks.py
-a---         204.00 B                 ├── __init__.py
d----          3.45 KB             mail_sender
-a---          3.45 KB                 ├── notifier.py
-a---           0.00 B                 ├── __init__.py
d----         907.00 B         api
-a---         907.00 B             ├── __init__.py
d----        108.33 KB             v1
-a---        108.33 KB                 ├── base_api.py
-a---           0.00 B                 ├── __init__.py
d----        505.57 KB                 endpoints
-a---         60.17 KB                     ├── product.py
-a---         50.88 KB                     ├── characteristic.py
-a---         34.30 KB                     ├── category.py
-a---        303.13 KB                     ├── platform.py
-a---         46.69 KB                     ├── collection.py
-a---         10.40 KB                     ├── photo.py
-a---           0.00 B                     ├── __init__.py
d----        162.67 KB         docs
-a---          1.93 KB             ├── load_docs.py
-a---         12.63 KB             ├── development.jpg
-a---        128.49 KB             ├── readme_logo.png
-a---         19.62 KB             ├── responses_variants.py
-a---           0.00 B             ├── __init__.py
d----         19.99 KB             descriptions
-a---          2.56 KB                 ├── code_style_integra.md
-a---          8.71 KB                 ├── api_description_prod.md
-a---          8.72 KB                 ├── api_description_dev.md
d----           1.00 B         db
-a---           1.00 B             ├── __init__.py
d----         65.96 KB             dao
-a---         64.83 KB                 ├── base_dao.py
-a---          1.12 KB                 ├── __init__.py
d----        242.78 KB                 catalog
-a---         79.30 KB                     ├── product.py
-a---         25.22 KB                     ├── characteristic.py
-a---         25.18 KB                     ├── category.py
-a---         69.94 KB                     ├── platform.py
-a---         184.00 B                     ├── variant.py
-a---         30.01 KB                     ├── collection.py
-a---         12.51 KB                     ├── photo.py
-a---         450.00 B                     ├── __init__.py
d----         17.71 KB             models
-a---          2.03 KB                 ├── enums_models.py
-a---          6.25 KB                 ├── associations.py
-a---          7.54 KB                 ├── base_sql.py
-a---          1.89 KB                 ├── __init__.py
d----         42.75 KB                 tables
-a---          4.53 KB                     ├── product.py
-a---          2.36 KB                     ├── characteristic.py
-a---          3.42 KB                     ├── category.py
-a---         19.81 KB                     ├── platform.py
-a---          7.72 KB                     ├── service_notifier.py
-a---         910.00 B                     ├── variant.py
-a---          2.83 KB                     ├── collection.py
-a---          1.19 KB                     ├── photo.py
-a---           0.00 B                     ├── __init__.py
d----          9.98 KB             sessions
-a---          1.29 KB                 ├── utils.py
-a---          8.66 KB                 ├── _session.py
-a---          23.00 B                 ├── __init__.py
d----          3.16 KB             migrations
-a---          38.00 B                 ├── README
-a---          2.50 KB                 ├── env.py
-a---         635.00 B                 ├── script.py.mako
-a---           0.00 B                 ├── __init__.py
d----         52.85 KB                 versions
-a---          1.38 KB                     ├── 2025-05-30_13-23-36_delete_secret_key2.py
-a---         47.01 KB                     ├── 2025-05-27_15-54-52_new_start.py
-a---         904.00 B                     ├── 2025-05-28_11-41-26_null_true_to_sku_for_product.py
-a---          1.57 KB                     ├── 2025-05-30_12-06-33_delete_secret_key.py
-a---          2.01 KB                     ├── 2025-07-13_16-12-39_auto_migration_20250713_161237.py
-a---           0.00 B                     ├── __init__.py
d----          3.66 KB             schemas
-a---          3.66 KB                 ├── default_schemas.py
-a---           0.00 B                 ├── __init__.py
d----         63.04 KB                 models_schemas
-a---          6.85 KB                     ├── product.py
-a---          5.40 KB                     ├── characteristic.py
-a---          3.92 KB                     ├── category.py
-a---         29.59 KB                     ├── platform.py
-a---          5.03 KB                     ├── service_notifier.py
-a---         984.00 B                     ├── response.py
-a---          4.54 KB                     ├── collection.py
-a---          6.74 KB                     ├── photo.py
-a---           0.00 B                     ├── __init__.py
d----         43.88 KB         core
-a---          8.10 KB             ├── config.py
-a---         35.78 KB             ├── middlewares.py
-a---           0.00 B             ├── __init__.py
d----         23.25 KB         utils
-a---          8.19 KB             ├── http_exceptions.py
-a---          1.40 KB             ├── reg_exceptions.py
-a---          4.06 KB             ├── exceptions.py
-a---          9.60 KB             ├── logger.py
-a---           0.00 B             ├── __init__.py
d----         16.15 KB     make-scripts
-a---          4.60 KB         ├── anwill-auto-ssh-linux.sh
-a---          5.26 KB         ├── anwill-auto-ssh.ps1
-a---         444.00 B         ├── anwill-auto-ssh-windows.ps1
-a---          2.38 KB         ├── setup.sh
-a---          2.74 KB         ├── setup.cmd
-a---         759.00 B         ├── anwill-auto-ssh-run-windows.cmd
d----          1.22 KB     tests
-a---          28.00 B         ├── test_product_api.py
-a---          1.20 KB         ├── test_client.py
-a---           0.00 B         ├── __init__.py
d----         18.04 KB     deploy
-a---         984.00 B         ├── compose.catalog.pstgr.dev.yml
-a---          3.43 KB         ├── compose.catalog.full.prod.yml
-a---         770.00 B         ├── compose.catalog.pstgr.prod.yml
-a---          2.58 KB         ├── compose.catalog.app.dev.yml
-a---          5.35 KB         ├── compose.catalog.full.dev.yml
-a---         821.00 B         ├── compose.catalog.app.prod.yml
-a---          2.08 KB         ├── compose.infrastructure.dev.yml
-a---          2.08 KB         ├── compose.infrastructure.prod.yml
d----           0.00 B         nginx_confings
d----         18.88 KB             dev_server-82.97.249.222
-a---          1.56 KB                 ├── 2tb.anwill.fun.conf
-a---          1.15 KB                 ├── 2rabbit.anwill.fun.conf
-a---          1.83 KB                 ├── 2flower.anwill.fun.conf
-a---          2.32 KB                 ├── 2widget.anwill.fun.conf
-a---          4.32 KB                 ├── 2id.anwill.fun.conf
-a---          1.89 KB                 ├── 2minio.anwill.fun.conf
-a---          1.54 KB                 ├── 2ui-kit.anwill.fun.conf
-a---          1.33 KB                 ├── 2port.anwill.fun.conf
-a---          2.94 KB                 ├── 2api.anwill.fun.conf
d----         20.65 KB             prod_server-45.9.73.208
-a---          2.30 KB                 ├── widget.anwill.fun.conf
-a---          1.82 KB                 ├── flower.anwill.fun.conf
-a---         846.00 B                 ├── mail.anwill.fun.conf
-a---          2.94 KB                 ├── api.anwill.fun.conf
-a---          1.84 KB                 ├── minio.anwill.fun.conf
-a---          1.46 KB                 ├── ui-kit.anwill.fun.conf
-a---         985.00 B                 ├── anwill.fun.conf
-a---          1.47 KB                 ├── port.anwill.fun.conf
-a---          1.56 KB                 ├── tb.anwill.fun.conf
-a---          1.15 KB                 ├── rabbit.anwill.fun.conf
-a---          4.32 KB                 ├── id.anwill.fun.conf
