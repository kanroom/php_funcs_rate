#!/usr/bin/env python3
# Copyright (c) 2017 Kandia Roman. All rights reserved.
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version. It is provided for educational
# purposes and is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.

import os
import queue
import sys
import time
import collections
import re
import optparse
from os.path import join
from threading import Thread, Lock


time_start = time.time()
old_len_text = 0
count_files = 0


def main():
    opts, args, allowed_extensions = options()
    all_funcs = {}
    errors = []
    threads = opts.threads
    recurse = opts.recurse
    print_in_line("Getting files.")
    filelist = get_files(args, recurse, allowed_extensions)
    files_left = len(filelist)
    work_queue = queue.PriorityQueue()
    results_queue = queue.Queue()
    for thread in range(threads):
        worker = Worker(work_queue, results_queue, files_left)
        worker.daemon = True
        worker.start()
    results_thread = Thread(
                        target=lambda: gather_results(results_queue, all_funcs, errors))
    results_thread.daemon = True
    results_thread.start()
    for filename in filelist:
        work_queue.put(filename)
    work_queue.join()
    results_queue.join()
    print_in_line("End processing.", False)
    output_funcs(all_funcs, opts, args[0])
    if errors:
        error_file = "php_funcs_rate.log"
        errors_message = "There was {0} {1} while processing the {2}. See file {3}.".format(
                                                          len(errors), plural(len(errors), "errors", "error"),
                                                          plural(count_files, "files", "file"), error_file)
        print(errors_message)
        output_errors(errors, error_file)
    execution_time()


def gather_results(results_queue, all_funcs, errors):
    """Gathering all results from the job of the class 'Worker'.
    """
    while True:
        try:
            results = results_queue.get()
            funcs = results[0]
            error = results[1]
            if funcs:
                update_funcs(all_funcs, funcs)
            if error:
                errors.append(error)
        finally:
            results_queue.task_done()


class Worker(Thread):


    old_len_text_lock = Lock()

    def __init__(self, work_queue, results_queue, files_left):
            super().__init__()
            self.work_queue = work_queue
            self.results_queue = results_queue
            self.files_left = files_left


    def run(self):
        global count_files
        while True:
            try:
                filename = self.work_queue.get()
                with Worker.old_len_text_lock:
                    text = "File processing (files left - {0}): {1}.".format(str(self.files_left), filename)
                    print_in_line(text)
                    self.process_file(filename)
                    self.files_left -= 1
                    count_files += 1
            finally:
                self.work_queue.task_done()


    def process_file(self, filename):
        """Processing and extracting from the file php functions and calculate their occurance.
        """
        results = [None, None]
        NORMAL, START_MEMORIZE, STOP_MEMORIZE = range(3)
        OCCUR, DESCRIPTION = 0, 1
        state = NORMAL
        function = ""
        funcs = collections.defaultdict(list)
        # Define valid previous symbols.
        pre_symbols = " (!@&\n\t\r"
        comments = ("/**", "/*", "*", "//")
        # Define state of the php class.
        php_class = 0
        f = None
        try:
            f = open(filename, encoding="utf8")
            for index, line in enumerate(f, start=1):
                # Skip all comments.
                if line.strip().startswith(comments):
                    continue
                # If we entrance in php class,
                # then change its state.
                if line.strip().startswith("class"):
                    php_class = 1
                    continue
                # If function defined in one of the processed files,
                # then it's a core's function.
                if line.strip().startswith("function") and not php_class:
                    func = re.findall("function[\s+]([&\w]+)(?=\()", line)
                    if func:
                        func = func.pop()
                        description = "core function - defined in " + filename + " on line " + str(index)
                        try:
                            funcs[func + "()"][DESCRIPTION] = description
                        except IndexError:
                            funcs[func + "()"] = [0, description]
                    continue
                for i, c in enumerate(line):
                    if php_class:
                        if c == "{":
                            php_class += 1
                        elif c == "}":
                            php_class -= 1
                    if state == NORMAL:
                        pre_symbol = line[i - 1]
                        # If character is a valid first character of the php functions name,
                        # and previous symbol is a valid previous symbol.
                        if is_valid_func_name(c) and pre_symbol in pre_symbols:
                            function += c
                            state = START_MEMORIZE
                            continue
                    if state == START_MEMORIZE:
                        if is_valid_char(c):
                            function += c
                        elif c == "(":
                            state = STOP_MEMORIZE
                        else:
                            function = ""
                            state = NORMAL
                    if state == STOP_MEMORIZE:
                        if is_valid_func_name(function):
                            try:
                                funcs[function + "()"][OCCUR] += 1
                            except IndexError:
                                funcs[function + "()"] = [1, ""]
                        function = ""
                        state = NORMAL
            if funcs:
                results.insert(0, funcs)
        except (IOError, OSError, UnicodeDecodeError) as err:
            time_error = time.time()
            error = "{0} -- {1} in file: {2}".format(time.strftime("%Y-%m-%d %H:%M:%S",
                                                     time.gmtime(time_error)), err, filename)
            results.insert(1, error)
        finally:
            if f is not None:
                f.close()
        self.results_queue.put(results)


def print_in_line(text, print_in_line=True):
    """Printing text in the same line of the terminal.
    """
    global old_len_text
    if print_in_line:
        end = "\r"
    else:
        end = "\n"
    len_text = len(text)
    if len_text < old_len_text:
        print(text + " " * (old_len_text - len_text), end=end)
    elif len_text >= old_len_text:
        print(text, end=end)
    old_len_text = len_text


def waiting(end=False, text="Please wait"):
    """Animation of the three points after the text - simulating waiting effect.
    """
    dot = ""
    background = "   "
    while not end:
        print(text + dot + background, end="\r")
        dot += "."
        if len(dot) > 3:
            dot = ""
        time.sleep(1)


def update_funcs(d, other):
    """Update functions represented by the dictionary, which consists of key - string and value - list.
    """
    OCCUR, DESCRIPTION = 0, 1
    for key, ls in other.items():
        if key not in d.keys():
            d[key] = ls
        elif key in d.keys():
            d[key][OCCUR] += ls[OCCUR]
            if d[key][DESCRIPTION] == "" and d[key][DESCRIPTION] != ls[DESCRIPTION]:
                d[key][DESCRIPTION] = ls[DESCRIPTION]


def count(string, match, start=None, end=None, case=True):
    """Returns how much match in string, considering or not case of the characters.

    >>> string = "Hello world!"
    >>> count(string, "Hello")
    1
    >>> count(string, "hello")
    0
    >>> count(string, "hello", case=False)
    1
    """
    if match == "":
        return len(string) + 1
    count = 0
    if not start:
        start = 0
    if not end:
        end = len(string)
    if not case:
        string = string.lower()
        match = match.lower()
    while True:
        if string.find(match, start, end) != -1:
            count += 1
            start = string.find(match, start) + len(match)
        else:
            break
    return count


def plural(count, plural, singular):
    """Returns plural or singular string, depending of the count variable.
    """
    if count != 1:
        return plural
    else:
        return singular


def is_valid_func_name(name):
    """Checks if name is a valid php function name.
    """
    first_char = name[0]
    # A valid php function name starts with a letter or undescore.
    if not first_char.isalpha() and first_char != "_":
        return False
    for c in name:
        if is_valid_char(c):
            continue
        else:
            return False
    return True


def is_valid_char(char):
    """Checks if char is a valid php function's character.
    """
    if len(char) == 1:
        if not char.isalnum() and char != "_":
            return False
        return True
    else:
        error = "Length of the character {0} must be equivalent to 1".format(char)
        print(error)
        return False


def output_errors(errors, filename):
    """Outputting errors in the file.
    """
    f = None
    try:
        f = open(filename, "w", encoding="utf8")
        for error in errors:
            f.write(error)
            f.write("\n")
    except TypeError as err:
        print("Type error:", err)
    except EnvironmentError as err:
        print("Error: failed to save {0}: {1}!".format(filename, err))
        return True
    finally:
        if f is not None:
            f.close()


def output_funcs(funcs, opts, filename):
    """Outputting functions and organize their sorting.
    """
    if funcs:
        output = opts.outputfuncs
        keys_lists = []
        sort = opts.sortfuncs
        i = 1
        mx = max(list(funcs.values()))
        len_occur = len(str(mx[0]))
        len_func = max_len_key(funcs)
        len_index = len(str(len(funcs)))
        # Organizing sorting.
        for key, values in funcs.items():
            index = "{0:>{1}}".format(i, len_index)
            function = "{0:<{1}}".format(key, len_func)
            occur = "{0:>{1}}".format(values[0], len_occur)
            description = "{0}".format(values[1])
            if sort == "functions":
                sortkey = function
            elif sort == "occurs":
                sortkey = occur
            elif sort == "index":
                sortkey = i
            keys_list = (sortkey, "{index} {function} occurs {occur} - {description}".format(**locals()))
            keys_lists.append(keys_list)
            i += 1
        # Output.
        if output == "both" or output == "terminal":
            for key, line in sorted(keys_lists):
                try:
                    print(line)
                except UnicodeEncodeError as err:
                    print(err)
        if output == "both" or output == "infile":
            if not filename.endswith(".pfr"):
                filename += ".pfr"
            f = None
            try:
                f = open(filename, "w", encoding="utf8")
                for key, line in sorted(keys_lists):
                    f.write(line)
                    f.write("\n")
            except TypeError as err:
                print("Type error:", err)
            except EnvironmentError as err:
                print("Error: failed to save {0}: {1}!".format(filename, err))
                return True
            else:
                print("Saved {0} {1} to {2}".format(len(funcs),
                      plural(len(funcs), "functions", "function"), filename))
            finally:
                if f is not None:
                    f.close()
    else:
        print("There are no functions at all!")


def get_files(args, recurse, allowed_extensions):
    """Getting all files from the defined path or from the args.
    """
    filelist = []
    for arg in args:
        if os.path.isfile(arg):
            if arg.endswith(allowed_extensions):
                filelist.append(arg)
        elif recurse:
            for root, dirs, files in os.walk(arg):
                for filename in files:
                    fullname = join(root, filename)
                    if fullname.endswith(allowed_extensions):
                        filelist.append(fullname)
    return filelist


def max_len_key(dict):
    """Returns maximal length key of the represented dictionary.

    >>> dict = {"first": 5, "second": 6}
    >>> max_len_key(dict)
    6
    """
    max_len_key = 0
    for k in dict.keys():
        if len(k) > max_len_key:
            max_len_key = len(k)
    return max_len_key


def execution_time():
    """Prints how much time was spent, to the moment when this function was called.
    """
    global time_start
    time_end = time.time()
    execution_time = time_end - time_start
    directive = ""
    if execution_time > 60:
        # Converting seconds in to minutes and seconds.
        execution_time = time.strftime("%M m. %S s.", time.gmtime(execution_time))
    print("Execution time: ", execution_time, directive)


def options():
    usage = """
%prog [options] name1 [name2 [... nameN]]\n
names are filenames or paths; paths only make sense with the -r option set

Processing files with php-code,
extracting from these files functions and
calculating their occurrence. In addition,
if one of the extracted function is defined
in one of the processed files, the program
will consider this function as a kernel function
and memorize where it was defined.
Program supports multithreading."""

    output_list = "terminal infile both".split()
    sort_list = "functions occurs index".split()
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("-r", "--recurse", dest="recurse",
                      default=False, action="store_true",
                      help="recurse into subdirectories")
    parser.add_option("-e", "--extensions", dest="extensions",
                      action="store", type="str", default=(".php"),
                      help="define allowed extensions of the files [default: %default]\n"
                           "if defined extensions more then one, then separate them with slash: .inc/.module/.tpl/.html")
    parser.add_option("-t", "--threads", dest="threads", default=1,
                      type="int",
                      help=("the number of threads to use (1..20) [default: %default]"))
    parser.add_option("-s", "--sort", dest="sortfuncs",
                      action="store", choices=sort_list, default="functions",
                      help=("order the outputted functions by functions, occurs or index [default: %default]"))
    parser.add_option("-o", "--output", dest="outputfuncs",
                      action="store", choices=output_list, default="infile",
                      help=("output results on terminal or infile (or both) [default: %default]"))

    opts, args = parser.parse_args()
    allowed_extensions = (opts.extensions,)
    # If was added additional extensions.
    if ".php" not in allowed_extensions:
        allowed_extensions = tuple(opts.extensions.split("/")) + (".php",)
    if len(args) == 0:
        parser.error("at least one path must be specified")
    if (not opts.recurse and
        not any([os.path.isfile(arg) for arg in args])):
        parser.error("at least one file must be specified; or use -r")
    elif (not opts.recurse and [os.path.isfile(arg) for arg in args if not arg.endswith(allowed_extensions)]):
        invalid_files = []
        for arg in args:
            if os.path.isfile(arg) and not arg.endswith(allowed_extensions):
                invalid_files.append(arg)
        if invalid_files:
            parser_error = "{0} - {1} not {2} with allowed extension".format(", ".join([f for f in invalid_files]),
                                                                         plural(len(invalid_files), "are", "is"),
                                                                         plural(len(invalid_files), "files", "file"))
        else:
            parser_error = "if was defined path use -r"
        parser.error(parser_error)
    if not (1 <= opts.threads <= 20):
        parser.error("thread count must be 1..20")
    return opts, args, allowed_extensions


main()