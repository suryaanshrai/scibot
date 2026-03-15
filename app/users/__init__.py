"""
app.users — user management, authentication, and per-user configuration.

Public sub-modules
------------------
database       : SQLite connection and schema initialisation
crypto         : PBKDF2 password hashing and Fernet JSON encryption
users          : create_user / authenticate / delete_user / list_users / update_password
collections_db : CRUD helpers for the collections table
config         : per-user encrypted config storage and effective-config resolution
"""
