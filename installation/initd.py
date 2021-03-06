# -*- mode: python; encoding: utf-8 -*-
#
# Copyright 2012 Jens Lindström, Opera Software ASA
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
# License for the specific language governing permissions and limitations under
# the License.

import os
import os.path
import json
import pwd
import grp
import subprocess

import installation

created_file = []
renamed = []

rclinks_added = False
servicemanager_started = False

def restart(identity="main"):
    print
    print "Restarting service manager ..."

    try:
        subprocess.check_call(["service", "critic-%s" % identity, "restart"])
    except subprocess.CalledProcessError:
        return False

    return True

def install(data):
    global servicemanager_started, rclinks_added

    source_path = os.path.join(installation.root_dir, "installation", "templates", "initd")
    target_path = os.path.join("/etc", "init.d", "critic-main")

    with open(target_path, "w") as target:
        created_file.append(target_path)

        os.chmod(target_path, 0755)
        os.chown(target_path, installation.system.uid, installation.system.gid)

        with open(source_path, "r") as source:
            target.write((source.read().decode("utf-8") % data).encode("utf-8"))

    subprocess.check_call(["update-rc.d", "critic-main", "defaults"])
    rclinks_added = True

    subprocess.check_call([target_path, "start"])
    servicemanager_started = True

    return True

def upgrade(arguments, data):
    source_path = os.path.join(installation.root_dir, "installation", "templates", "initd")
    target_path = os.path.join("/etc", "init.d", "critic-main")
    backup_path = os.path.join(os.path.dirname(target_path), "_" + os.path.basename(target_path))

    source = open(source_path, "r").read().decode("utf-8") % data
    target = open(target_path, "r").read().decode("utf-8")

    system_uid = pwd.getpwnam(data["installation.system.username"]).pw_uid
    system_gid = grp.getgrnam(data["installation.system.groupname"]).gr_gid

    if source != target:
        def generateVersion(label, path):
            if label == "updated":
                with open(path, "w") as target:
                    target.write(source.encode("utf-8"))

        update_query = installation.utils.UpdateModifiedFile(
            arguments,
            message="""\
The SysV init script is about to be updated.  Please check that no local
modifications are being overwritten.

  Current version: %(current)s
  Updated version: %(updated)s

Please note that if the modifications are not installed, the system is
likely to break.
""",
            versions={ "current": target_path,
                       "updated": target_path + ".new" },
            options=[ ("i", "install the updated version"),
                      ("k", "keep the current version"),
                      ("d", ("current", "updated")) ],
            generateVersion=generateVersion)

        write_target = update_query.prompt() == "i"
    else:
        write_target = False

    if write_target:
        print "Updated file: %s" % target_path

        if not arguments.dry_run:
            os.rename(target_path, backup_path)
            renamed.append((target_path, backup_path))

            with open(target_path, "w") as target:
                created_file.append(target_path)
                os.chmod(target_path, 0755)
                os.chown(target_path, system_uid, system_gid)
                target.write(source.encode("utf-8"))

    if write_target or installation.files.sources_modified or installation.config.modified_files:
        if not arguments.dry_run:
            # Due to a Critic bug (see fix: "Fix recreation of /var/run/critic/IDENTITY after reboot")
            # it was possible that /var/run/critic/IDENTITY was accidentally recreated owned by root:root
            # instead of critic:critic (on reboot). If this had happened the service manager restart that
            # is done during upgrade would fail so upgrades always failed. Further, it was not possible
            # to write a migration script for this because migrations execute after the service manager
            # restart. Because of this the following 3 line workaround was necessary:
            import configuration
            if os.path.exists(configuration.paths.RUN_DIR):
                os.chown(configuration.paths.RUN_DIR, installation.system.uid, installation.system.gid)

            if not restart():
                return False

    return True

def undo():
    if servicemanager_started:
        subprocess.check_call([os.path.join("/etc", "init.d", "critic-main"), "stop"])

    map(os.unlink, created_file)

    for target, backup in renamed: os.rename(backup, target)

    if rclinks_added:
        subprocess.check_call(["update-rc.d", "critic-main", "remove"])

def finish():
    for target, backup in renamed: os.unlink(backup)
