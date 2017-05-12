#!/usr/bin/env python

# Scrapes all strands-project repositories for any readme files and wikis, and
# puts them into directories by repository

import requests
import errno
import getpass
import os
import json
import argparse
import subprocess
import shutil
import base64
import sys
import fnmatch
import yaml
import pypandoc
import urlparse
import re
import socket
import functools
import xml.etree.ElementTree as ET

os.environ.setdefault('PYPANDOC_PANDOC', '/usr/bin/pandoc')

def path_to_arr(path):
    arr = []
    while path:
        arr.append(os.path.basename(path))
        path = os.path.dirname(path)

    return list(reversed(arr))

def create_package_file(filetype="rst"):
    if os.path.isfile("docs/package.{}".format(filetype)):
        done = False
        while not done:
            resp = raw_input("docs/package.{} already exists. Overwrite? (y/n)\n".format(filetype))
            if resp == "y":
                done = True
                os.remove("docs/package.{}".format(filetype))
            else:
                print("Will not overwrite index. Exiting.")
                sys.exit(0)

    link_dict = {}
    desc_dict = {}
    # walk over the directory tree, and look for files with index, which we
    # will link to
    for subdir, dirs, files in os.walk("docs"):
        # take all chars after the 5th in the joined path, to remove docs/ from the string
        split = subdir.split('/')
        if len(split) == 1: # skip the top level directory
            continue
        dirpath = os.path.join(*split[1:])

        for file in files:
            if fnmatch.fnmatch(file, "*.xml"):
                fname, ext = os.path.splitext(file)
                with open(os.path.join(subdir, file), 'r') as f:
                    if fname == "package":
                        dict_key = dirpath
                    else:
                        dict_key = os.path.join(dirpath, fname)
                    desc_dict[dict_key] = get_package_xml_description(f.read())

            if fnmatch.fnmatch(file, "index.{}".format(filetype)):
                if not split[1] in link_dict:
                    link_dict[split[1]] = []
                # This will add links to the toplevel index and subpackage indexes
                link_dict[split[1]].append((dirpath, "[{0}]({1})".format(dirpath, os.path.join(dirpath, file))))

    package_file = "docs/packages.{}".format(filetype)
    with open(package_file, 'w') as f:
        
        f.write("# STRANDS Packages\n\nHere you can find all the documentation generated by the STRANDS project, aggregated from the github repositories.\n\n")
        for pkg_name in sorted(link_dict.keys()):
            link_list = link_dict[pkg_name]
            # The first entry in the list is the main package link. Make sure to
            # refer to the html page so things work (probably)
            f.write("## {0}\n\n".format(link_list[0][1].replace(filetype, "html")))
            # check base path and repeated subpackage path. e.g. in
            # aaf_deployment, the readme for info_termianl is at
            # aaf_deployment/info_terminal/readme.md, and package xml is at
            # aaf_deployment/info_terminal/info_terminal/package.xml
            if link_list[0][0] in desc_dict:
                f.write("{0}\n\n".format(desc_dict[link_list[0][0]]))
            elif os.path.join(link_list[0][0], os.path.basename(link_list[0][0])) in desc_dict:
                f.write("{0}\n\n".format(desc_dict[os.path.join(link_list[0][0], os.path.basename(link_list[0][0]))]))

            # Subsequent entries are subpackages
            for link in link_list[1:]:
                f.write("### {0}\n\n".format(link[1]))
                if link[0] in desc_dict:
                    f.write("{0}\n\n".format(desc_dict[link[0]]))
                elif os.path.join(link[0], os.path.basename(link[0])) in desc_dict:
                    f.write("{0}\n\n".format(desc_dict[os.path.join(link[0], os.path.basename(link[0]))]))

    pypandoc.convert_file(package_file, filetype, format="md", outputfile=package_file)

def get_oauth_header(private=False):
    # The first thing to do is get an OAuth token - we will use this in place of the
    # username and password in order to access public and private repositories in
    # the organisation. This allows for many more API requrests to be made

    # Check if we already have a token in the config file
    conf_file = os.path.join(os.path.expanduser("~"), ".strands_doc_oauth.tok")
    if not os.path.isfile(conf_file) or private:
        print("Couldn't find the token file, or private token requested. Will generate a new token.")

        user = raw_input("Enter your github username: ")
        password = getpass.getpass("Enter your github password:")

        scopes = ["repo"] if private else ["public_repo"]
        auth_data = json.dumps({"scopes": scopes, "note": "strands_documentation scraper {}".format(socket.gethostname())})
        auth = (requests.post("https://api.github.com/authorizations", data=auth_data, auth=(user, password))).json()

        # If we already got a token recently, we will receive an error message
        if "token" not in auth:
            print("Couldn't get Github auth token: {0}".format(auth["message"]))
            token = None
        else: # otherwise, save the token to a file so we can use it again later
            with os.fdopen(os.open(os.path.join(os.path.expanduser("~"), ".strands_doc_oauth.tok"), os.O_WRONLY | os.O_CREAT, 0o600), 'w') as handle:
                handle.write(auth["token"])
                token = auth["token"]
    else:
        with open(conf_file, 'r') as f:
            token = f.read()
        print("Found config file with token.")


    if token:
        header = {"Authorization": "token {0}".format(token)}
    else:
        print("Proceeding without auth token.")
        header = ""

    return header

def get_org_repo_dict(org, header=None):
    """get a list of all the repositories in the given organisation
    """

    print("https://api.github.com/orgs/{0}/repos?type=all".format(org))
    repo_rq = requests.get("https://api.github.com/orgs/{0}/repos?type=all".format(org), headers=header)
    repos = {repo_data["name"]: repo_data for repo_data in json.loads(repo_rq.text)}
    # If there are more than 30 repos, there will be multiple pages
    if "link" in repo_rq.headers:
        # keep getting the data until we reach the final page - we can deduce this
        # by there not being a link to the last page, because we are on it.
        while "last" in repo_rq.headers["link"]:
            print(repo_rq.headers["link"])
            # Get the URL for the next page by splitting the links up
            next_pg = repo_rq.headers["link"].split(',')[0].split(';')[0][1:-1]
            repo_rq = requests.get(next_pg, headers=header)
            repos.update({repo_data["name"]: repo_data for repo_data in json.loads(repo_rq.text)})

    return repos

def get_wiki(org_name, repo_name, filetype="rst"):
    """Check if a wiki exists, and if it does, clone it to the docs/repo_name/wiki
    """
    # to devnull so there's no output
    FNULL = open(os.devnull, 'w')
    # We can check if a wiki exists by calling git ls-remote. If it returns an
    # OK, then there is a wiki
    if subprocess.call(["git", "ls-remote", "https://github.com/{0}/{1}.wiki.git".format(org_name, repo_name)], stdout=FNULL, stderr=FNULL) == 0:
        wiki_dir = "docs/{0}/wiki".format(repo_name)
        # only clone if the wiki does not already exist
        if not os.path.isdir(wiki_dir):
            print("Wiki exists. Cloning...")
            subprocess.call(["git", "clone", "https://github.com/{0}/{1}.wiki.git".format(org_name, repo_name), wiki_dir])
            # delete the .git directory cloned along with the wiki
            shutil.rmtree(os.path.join(wiki_dir, ".git"))
            # rename the Home file to index so it works properly with mkdocs
            #os.rename(os.path.join(wiki_dir, "Home.md"), os.path.join(wiki_dir, "index.md"))

        # The wiki is written in markdown, so need to convert it if the filetype
        # we're supposed to be using is different.
        if filetype != "md":
            for subdir, dirs, files in os.walk(wiki_dir):
                for wiki_file in files:
                    if fnmatch.fnmatch(wiki_file, "*.md"):
                        file_path = os.path.abspath(os.path.join(subdir, wiki_file))
                        new_file_path = "{}.{}".format(os.path.splitext(file_path)[0], filetype)
                        print("Converting wiki file {} to {}".format(file_path, filetype))
                        pypandoc.convert_file(file_path, filetype, format="md", outputfile=new_file_path)
                        # remove the original markdown file
                        os.remove(file_path)

def get_repo_files(org_name, repo_name, match_ext=[], match_filename=[], match_full=[]):
    """Get files in the given repository which have extensions matching any in the
    given match_ext list, or filenames (without extensions) which match any in
    the given match_filename list. Full filenames (filename + extension) are
    compared to entries in match_full.

    A dictionary where the file path in the repository is the key, and the item
    returned by the github api is the value will be returned.

    """
    if not match_ext and not match_filename and not match_full:
        return {}
    global org
    # The main readme file in the repo is easily retrieved, but just do this using the tree instead
    #readme_rq = requests.get("https://api.github.com/repos/{0}/{1}/readme".format(org, repo_name), headers=header)

    # We also need to look at the whole repository to find the readmes for
    # subdirectories, since there are many such cases. First, get the current
    # commit sha on the default branch
    sha_rq = requests.get("https://api.github.com/repos/{0}/{1}/commits".format(org_name, repo_name), headers=header)
    latest_sha = json.loads(sha_rq.text)[0]["sha"]
    # Use that sha to get the commit tree
    tree_rq = requests.get("https://api.github.com/repos/{0}/{1}/git/trees/{2}?recursive=1".format(org_name, repo_name, latest_sha), headers=header)
    repo_tree = json.loads(tree_rq.text)

    # Look through the tree and try to find things which are likely to be readme-type files
    print("Looking for files matching strings {0}".format(match_ext + match_filename + match_full))
    # We gather readmes here so we can remap any links in them, which we need to
    # do because we will change the filenames to make the documentation appear
    # in a nicer way. Gather them in a dict which will group multiple readmes in
    # the same subdirectory, which we want to handle differently.
    matching = {}
    for item in repo_tree["tree"]:
        lower_fname, lower_ext = os.path.splitext(os.path.basename(item["path"].lower()))
        fname_matches = map(lambda x: lower_fname == x.lower(), match_filename)
        ext_matches = map(lambda x: lower_ext == x.lower(), match_ext)
        full_matches = map(lambda x: lower_fname + lower_ext == x.lower(), match_full)
        if any(fname_matches) or any(ext_matches) or any(full_matches):
            matching[item["path"]] = item

    return matching

def files_to_subpackages(file_dict):
    """Converts a dict of path-item pairs received from get_repo_files to a dict
    where files that are in the same subpackage can be found in a list under the
    key with the subpackage name.

    """
    new_dict = {}
    for file_path in file_dict.keys():
        # The first directory in the path we get is a subdirectory in the
        # repo. Populate a new dict with readmes from each subdirectory
        # under the same key
        split_path = path_to_arr(os.path.dirname(file_path))
        key = split_path[0] if split_path else "index"
        if key not in new_dict:
            new_dict[key] = []
        # path, item pair
        new_dict[key].append((file_path, file_dict[file_path]))

    return new_dict

def get_package_xml_description(xml):
    root = ET.fromstring(xml)
    return root.findall("description")[0].text

def html_to_file(dataset_name, url, pandoc_extra_args=None, dataset_conf=None, filetype="rst"):
    """Converts a url or file from html to the given pandoc filetype, saving any
    images in the html to an image directory.

    """
    print("Processing dataset {0} with url {1}".format(dataset_name, url))
    # Should actually be using html parser...
    link_re =  re.compile('href="(\S*)"')
    # https://stackoverflow.com/questions/1028362/how-do-i-extract-html-img-sources-with-a-regular-expression#1028370
    image_re = re.compile('<img[^>]+src="([^">]+)"')

    url_split = urlparse.urlparse(url)
    orig_path = url_split.path
    # trim the path to get the base path for the page, to replace
    # relative paths in the html
    trimmed_path = os.path.dirname(orig_path)
    base_url = url.replace(orig_path, trimmed_path)

    # verify=false is dangerous as it ignores ssl certificates, but
    # we're not doing anything which has security risks associated.
    response = requests.get(url, verify=False)
    if response.status_code == 200:
        html_text = response.text
    else:
        print("Response code was not 200, something is probably wrong with this website.")
        return "Could not retrieve this page."

    # We want to preserve images in the documentation, so we will download all
    # the images on the page. Then, we'll replace the image references to the
    # web with ones to the images directory we save them in
    image_base_path = os.path.abspath("docs/datasets/images/{0}".format(dataset_name))
    if not os.path.isdir(image_base_path):
        os.makedirs(image_base_path)

    def image_replace(match):
        image_link = match.group(1)
        # This is a relative link, so need to construct the full url
        if not match.group(1).startswith("http") and not match.group(1).startswith("www"):
            image_link = base_url + "/" + image_link
        
        image_name = os.path.basename(urlparse.urlparse(image_link).path)
        image_outfile = os.path.join(image_base_path, image_name)
        
        print("downloading {} from {}".format(image_name, image_link))

        with open(image_outfile, 'w') as f:
            img_resp = requests.get(image_link, verify=False)
            f.write(img_resp.content)
            
        return match.group(0).replace(match.group(1), "images/{0}/{1}".format(dataset_name, image_name))

    html_text = image_re.sub(image_replace, html_text)

    try:
        # remove the directory if it's empty
        os.rmdir(image_base_path)
        print("There weren't any images on the page.")
    except OSError as ex:
        if ex.errno == errno.ENOTEMPTY:
            pass # this means there were images downloaded

    pandoc_args = ["--no-wrap"]
    if pandoc_extra_args:
        pandoc_args.extend(pandoc_extra_args)

    file_text = pypandoc.convert_text(html_text, filetype, format="html", extra_args=pandoc_args).encode('utf-8')
    
    # Also want to make sure that if there is a direct link to a dataset on the
    # page that it is converted to link to the markdown file we will generate
    # here rather than going to somewhere else on the web. This mostly applies
    # to the index page. Flatten the dictionary so that the key-value pairs are
    # now the base url for the dataset page, and the dataset key (which
    # corresponds to the markdown filename)
    url_dict = {dataset_conf[key]["url"]: key for key in dataset_conf.keys()}
    for url in url_dict.keys():
        file_text = file_text.replace(url, "{}.html".format(url_dict[url]))

    return file_text

def create_dataset_docs(dataset_conf, filetype="rst"):
    """Creates dataset docs from a configuration provided, which should be found in datasets/datasets.yaml
    Will convert html pages to markdown files.
    """
    if not os.path.isdir("docs/datasets"):
        os.makedirs("docs/datasets")

    for dataset in datasets.keys():
        with open("docs/datasets/{}.{}".format(dataset, filetype), 'w') as f:
            extra_args = None
            if "pandoc_extra_args" in datasets[dataset] and datasets[dataset]["pandoc_extra_args"]:
                extra_args = datasets[dataset]["pandoc_extra_args"]
            f.write(html_to_file(dataset, datasets[dataset]["url"], extra_args, dataset_conf, filetype))

def generate_rst_index(index_config):
    """Generate a series of TOC sections to insert into the index.rst.
    """
    rst_files = []
    rst_dirs = set()
    for subdir, dirs, files in os.walk("docs"):
        for doc_file in files:
            # ignore files in the docs directory like index, packages and setup
            if fnmatch.fnmatch(doc_file, "*.rst") and subdir != "docs":
                # remove docs/ and .rst before appending
                rst_files.append(os.path.join(subdir, doc_file)[5:-4])
                rst_dirs.add(subdir)

    # Base string for toctree. Use format to name the toctree
    toctree_base = """.. toctree::
   :maxdepth: 1
   :caption: {}:

"""
    
    toc_groups = {}
    for toc_group in index_config:
        top_key = toc_group.keys()[0]
        toc_groups[top_key] = {"toc_string": toctree_base.format(toc_group[top_key]["caption"]),
                               "target_dirs": toc_group[top_key]["dirs"],
                               "toc_files": []} # files to go in this group go here

    for rst_dir in rst_dirs:
        dirname = os.path.join(*rst_dir.split("/")[1:])
        toc_groups[dirname] = {"toc_string": toctree_base.format(dirname.replace("_", " ").replace("/", " ")),
                               "target_dirs": [dirname],
                               "toc_files": []} # files to go in this group go here

    # Go over all the rst files and put them into the correct TOC
    for rst in sorted(rst_files):
        # the base subdirectory of this rst file (i.e. the package it is in)
        base_dir = rst.split("/")[0]
        # Check all toc groups in the config to see if this file should be put
        # in a group or in the generic TOC
        for group_key in toc_groups.keys():
            # Looks through all the directories that are in the given toc group
            for toc_dir in toc_groups[group_key]["target_dirs"]:
                if os.path.dirname(rst) == toc_dir:
                    toc_groups[group_key]["toc_files"].append(rst)

    base_toc = toctree_base.format("Introduction")
    base_toc += "   setup\n   packages\n\n\n"

    group_tocs = ""

    # Process each group 
    for group_key in sorted(toc_groups.keys()):
        for toc_file in toc_groups[group_key]["toc_files"]:
            toc_groups[group_key]["toc_string"] += "   {}\n".format(toc_file)

        group_tocs += toc_groups[group_key]["toc_string"] + "\n\n"

    return base_toc + group_tocs

def write_rst_toc_to_index(config):
    # Modify index.rst TOC section so that all rst files are included in the documentation
    # Generate the indexes from config provided
    rst_index = generate_rst_index(config["rst_index_config"])

    with open("docs/index.rst", 'r+') as f:
        index = f.read()
        toc_re = re.compile("\.\. toctree::")
        # This is where the TOC starts currently
        toc_start = toc_re.search(index).start()

        # Create a new string with the non-TOC part of the file, and add on
        # the new TOC
        index = index[:toc_start] + rst_index
        f.seek(0)
        f.write(index)


def write_readme_files(repo_name, filetype="rst"):
    # We look for markdown files, as readmes on github for the strands
    # repositories are written in markdown
    readmes = get_repo_files(org, repo_name, match_ext=[".md"], match_filename=["readme"])
    subpkg_readmes = files_to_subpackages(readmes)

    for subpkg in subpkg_readmes.keys():
        print("processing {0}".format(subpkg))

        # The path we get in each item is something like
        # strands_navigation/topological_rviz_tools/readme.md. When using
        # mkdocs, this will generate the documentation in subheadings for each
        # subdirectory, whereas we would prefer it to be grouped under
        # strands_navigation. So, we will save the data in readme.md to
        # strands_navigation/topological_rviz_tools.{filetype}. In the case of packages
        # with multiple readmes, we will create a separate directory for them so
        # they are in their own section.
        base_path = os.path.join("docs", repo_name)

        multiple = False
        if len(subpkg_readmes[subpkg]) > 1:
            # sometimes the top level may have multiple files, but we don't want
            # to put them in a subdirectory
            if subpkg != "index":
                base_path = os.path.join(base_path, subpkg)
            multiple = True

        for readme in subpkg_readmes[subpkg]:
            # # Get a filename for the new readme file based on where it was in the directory tree.
            split_path = path_to_arr(os.path.dirname(readme[0]))
            if multiple:
                # There is more than one file in the subpackage
                lower_fname = os.path.splitext(os.path.basename(readme[0]))[0].lower()
                if len(split_path) <= 1:
                    # The file was at level 0 or 1 in the directory tree. If
                    # it was called readme, then we rename it to index.{filetype} so
                    # that it is used as a base page in the documentation.
                    # Otherwise, we keep its current name in lowercase.
                    if lower_fname == "readme":
                        fname = "index.{}".format(filetype)
                    else:
                        fname = lower_fname + ".{}".format(filetype)
                else:
                    # The path is long, so the file was nested deeper than
                    # level 1 in the tree. We will rename it to the name of
                    # the directory that it was in.
                    print("path is long: {0}".format(split_path))
                    fname = split_path[-1] + ".{}".format(filetype)
            else:
                # There is only one file in the subpackage. If the split
                # path length is zero, that means it was a toplevel readme,
                # so rename it to index so it's parsed differently by the
                # documentation code.
                if len(split_path) == 0:
                    fname = "index.{}".format(filetype)
                else:
                    # Otherwise, rename it to the name of the directory it
                    # was in.
                    fname = split_path[-1] + ".{}".format(filetype)

            # make sure a directory exists for the files
            path = os.path.join(base_path, fname)
            print("Saving {0} to {1}".format(readme[1]["path"], path))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))

            # Get the contents of the readme file from github and output them to a file
            file_rq = json.loads(requests.get(readme[1]["url"], headers=header).text)
            # decode and output the base64 string to file
            with open(path, 'w') as f:
                if filetype == "md":
                    f.write(base64.b64decode(file_rq["content"]))
                else:
                    f.write(pypandoc.convert_text(base64.b64decode(file_rq["content"]),
                                                  filetype,
                                                  format="md").encode('utf-8'))

if __name__ == '__main__':
    org = "strands-project"

    parser = argparse.ArgumentParser(description="Scrape documentation from the strands project repositories. This script should be run from the top level directory of strands_documentation.")
    parser.add_argument("--private", action="store_true", help="Include private repositories in the scrape. This requires the generation of an OAuth token for github.")
    # parser.add_argument("--pkgxml", action="store_true", help="Get descriptions of packages from the package.xml in each subdirectory of a repository. If set, the readme data will not be gathered. The files created by this are used by the package-index switch when generating the markdown file with descriptions of all packages")
    parser.add_argument("--nowiki", action="store_true", help="Skip cloning wikis for each package.")
    parser.add_argument("--package-index", action="store_true", help="Run after generating docs. Generate a readme in the docs directory, populating it with links to all the toplevel readmes in each directory in the docs directory. Basically a list of packages along with a description scraped from the package xml. Does not generate other docs.")
    parser.add_argument("--conf", default="./conf/conf.yaml", help="Config file to use for this docs generation. Can specify repositories to ignore. Default is strands_documentation/conf/conf.yaml directory.")
    parser.add_argument("--datasets", action="store_true", help="Generate markdown files for datasets specified in datasets/datasets.yaml. Files will be saved in the datasets directory and copied to the docs directory.")
    parser.add_argument("--single-package", action="store", type=str, help="Use to specify a single package to update")
    parser.add_argument("--filetype", action="store_true", default="rst", help="Specify the filetype for output. This should be a valid pandoc output format. This is used to define which format files scraped from the github repositories, or from the web in the case of datasets, are converted to when they are copied to the docs directory. Default is to output to rst, for use in readthedocs.")
    parser.add_argument("--rst-index-toc", action="store_true", help="Regenerate the rst TOC for the docs/index.rst file")

    args = parser.parse_args()

    with open(args.conf, 'r') as f:
        config = yaml.safe_load(f.read())
    ignore_repos = config["ignore_repos"]

    if args.datasets:
        datasets = {}
        with open("conf/datasets.yaml") as f:
            datasets = yaml.safe_load(f.read())["datasets"]

        create_dataset_docs(datasets, filetype=args.filetype)
        sys.exit(0)

    if args.package_index:
        create_package_file()
        sys.exit(0)

    if args.rst_index_toc:
        write_rst_toc_to_index(config)
        sys.exit(0)

    header = get_oauth_header(args.private)
    repos = get_org_repo_dict(org, header)

    # This is where the bulk of the work is done. We check each repository for
    # readme files and see if it has a wiki. If we find files there, we copy them
    # and put them in directories corresponding to the name of the repository
    packages = sorted(repos.keys()) if not args.single_package else [args.single_package]
    for repo_name in packages:
        print("-------------------- {0} --------------------".format(repo_name))
        if repo_name in ignore_repos:
            print("ignoring repo".format(repo_name))
            continue

        # Clone the wiki repo for this repo into the docs subdirectory for the repo
        if not args.nowiki:
            get_wiki(org, repo_name, filetype=args.filetype)

        # Find readme (or markdown) files in the repository and write them to
        # the subdirectory, preserving some of the directory structure of the repo.
        write_readme_files(repo_name, filetype=args.filetype)

        package_xml = get_repo_files(org, repo_name, match_full=["package.xml".format(repo_name)])
        subpkg_xml = files_to_subpackages(package_xml)

        base_path = os.path.join("docs", repo_name)
        for subpkg in subpkg_xml.keys():
            multiple = len(subpkg_xml[subpkg]) > 1
            for pkg_xml in subpkg_xml[subpkg]:
                split_path = path_to_arr(os.path.dirname(pkg_xml[0]))
                if multiple:
                    # There is more than one file in the subpackage
                    if len(split_path) <= 1:
                        fname = "package.xml"
                    else:
                        # The path is long, so the file was nested deeper than
                        # level 1 in the tree. We will rename it to the name of
                        # the directory that it was in.
                        print("path is long: {0}".format(split_path))
                        fname = split_path[-1] + ".xml"
                else:
                    # There is only one file in the subpackage. If the split
                    # path length is zero, that means it was a toplevel readme,
                    # so rename it to index so it's parsed differently by the
                    # documentation code.
                    if len(split_path) == 0:
                        fname = "package.xml"
                    else:
                        # Otherwise, rename it to the name of the directory it
                        # was in.
                        fname = split_path[-1] + ".xml"

                if len(split_path) > 1:
                    path = os.path.join(base_path, os.path.join(*split_path[:-1]), fname)
                else:
                    path = os.path.join(base_path, fname)

                print("Saving {0} to {1}".format(pkg_xml[1]["path"], path))
                if not os.path.isdir(os.path.dirname(path)):
                    os.makedirs(os.path.dirname(path))

                # Get the contents of the package.xml file from github and output them to a file
                file_rq = json.loads(requests.get(pkg_xml[1]["url"], headers=header).text)
                with open(path, 'w') as f:
                    f.write(base64.b64decode(file_rq["content"]))

    create_package_file()
    if args.filetype == "rst":
        write_rst_toc_to_index(config)
