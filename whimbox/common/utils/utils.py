
import os, json
import sys
if sys.platform == 'win32':
    import win32gui, win32process, ctypes
import psutil
import numpy as np
from collections import OrderedDict
from typing import Union

from whimbox.common.logger import logger
from whimbox.common.path_lib import *
from whimbox.common.cvars import *


def load_json(json_name, folder_path) -> Union[dict,list]:
    """加载json.

    Args:
        json_name (str, optional): json文件名.包含后缀. Defaults to 'General.json'.
        folder_path (str, optional): json文件夹路径. Defaults to 'config\\settings'.
    Raises:
        FileNotFoundError

    Returns:
        dict: dict/list
    """
    all_path = os.path.join(ROOT_PATH, folder_path, json_name)
    try:
        return json.load(open(all_path, 'r', encoding='utf-8'), object_pairs_hook=OrderedDict)
    except:
        logger.critical(f"尝试读取{all_path}失败")
        raise FileNotFoundError(all_path)


def save_json(x, json_name, default_path, sort_keys=True):
    """保存json.

    Args:
        x (_type_): dict/list对象
        json_name (str, optional): 同load_json. Defaults to 'General.json'.
        default_path (str, optional): 同load_json. Defaults to 'config\\settings'.
        sort_keys (bool, optional): 是否自动格式化. Defaults to True.
    Raises:
        FileNotFoundError
    """
    all_path = os.path.join(default_path, json_name)
    try:
        json.dump(x, open(all_path, 'w', encoding='utf-8'), sort_keys=sort_keys, indent=2, ensure_ascii=False)
    except:
        logger.critical(f"尝试写入{all_path}失败")
        raise FileNotFoundError(all_path)


# verify administration
def is_admin():
    try:
        import sys
        if sys.platform == 'win32':
            return ctypes.windll.shell32.IsUserAnAdmin()
        else:
            return os.geteuid() == 0
    except Exception as e:
        logger.error(f"检查管理员权限失败: {e}")
        return False


# def get_active_window_process_name():
#     try:
#         pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
#         name = psutil.Process(pid[-1]).name()
#         if name:
#             return name
#         else:
#             return "unknown"
#     except:
#         pass


def verify_path(root):
    if not os.path.exists(root):
        verify_path(os.path.join(root, "../"))
        os.mkdir(root)
        print(f"dir {root} has been created")


# functions
def list_text2list(text: str) -> list:
    """str列表转列表.

    Args:
        text (str): _description_

    Returns:
        list: _description_
    """
    if text is not None:  # 判断是否为空
        try:  # 尝试转换
            rt_list = json.loads(text)
        except:
            rt_list = []

        if type(rt_list) != list:  # 判断类型(可能会为dict)
            rt_list = list(rt_list)

    else:
        rt_list = []

    return rt_list


def list2list_text(lst: list) -> str:
    """列表转str.

    Args:
        lst (list): _description_

    Returns:
        str: _description_
    """
    if lst is not None:  # 判断是否为空
        try:  # 尝试转换
            rt_str = json.dumps(lst, ensure_ascii=False)
        except:
            rt_str = str(lst)

    else:
        rt_str = str(lst)

    return rt_str


def list2format_list_text(lst: list, inline = False) -> str:
    if lst is not None:  # 判断是否为空
        try:  # 尝试转换
            rt_str = json.dumps(lst, sort_keys=False, indent=4, separators=(',', ':'), ensure_ascii=False)
        except:
            rt_str = str(lst)

    else:
        rt_str = str(lst)
    # print(rt_str)
    if inline:
        rt_str = rt_str.replace('\n', ' ')
    return rt_str


def is_json_equal(j1: str, j2: str) -> bool:
    """_summary_

    Args:
        j1 (str): _description_
        j2 (str): _description_

    Returns:
        bool: _description_
    """
    try:
        return json.dumps(json.loads(j1), sort_keys=True) == json.dumps(json.loads(j2), sort_keys=True)
    except:
        return False


def is_int(x):
    """_summary_

    Args:
        x (_type_): _description_

    Returns:
        _type_: _description_
    """
    try:
        int(x)
    except ValueError:
        return False
    else:
        return True


def is_number(s):
    """
    懒得写,抄的
    https://www.runoob.com/python3/python3-check-is-number.html
    """
    try:
        float(s)
        return True
    except ValueError:
        pass

    try:
        import unicodedata
        unicodedata.numeric(s)
        return True
    except (TypeError, ValueError):
        pass

    return False

def is_chinese(text: str) -> bool:
    return any('\u4e00' <= char <= '\u9fff' for char in text)

def float2str(n, decimal=3):
    """
    Args:
        n (float):
        decimal (int):

    Returns:
        str:
    """
    return str(round(n, decimal)).ljust(decimal + 2, "0")


def maxmin(x,nmax,nmin):
    """很好看懂(

    Args:
        x (_type_): _description_
        nmax (_type_): _description_
        nmin (_type_): _description_

    Returns:
        _type_: _description_
    """
    x = min(x, nmax)
    x = max(x, nmin)
    return x


def round_list(x:list, n:int):
    for i in range(len(x)):
        x[i] = round(x[i], n)
    return x.copy()


def replace_text_format(text:str):
    """中文格式化.

    Args:
        text (str): _description_

    Returns:
        _type_: _description_
    """
    text = text.replace("：",":")
    text = text.replace("！","!")
    text = text.replace("？","?")
    text = text.replace("，",",")
    text = text.replace("。",".")
    text = text.replace("“","\"")
    text = text.replace("”","\"")
    text = text.replace("‘","\'")
    text = text.replace("’","\'")
    return text


def random_normal_distribution_int(a, b, n=3):
    """Generate a normal distribution int within the interval. Use the average value of several random numbers to
    simulate normal distribution.

    Args:
        a (int): The minimum of the interval.
        b (int): The maximum of the interval.
        n (int): The amount of numbers in simulation. Default to 3.

    Returns:
        int
    """
    if a < b:
        output = np.mean(np.random.randint(a, b, size=n))
        return int(output.round())
    else:
        return b


def ensure_time(second, n=3, precision=3):
    """Ensure to be time.

    Args:
        second (int, float, tuple): time, such as 10, (10, 30), '10, 30'
        n (int): The amount of numbers in simulation. Default to 5.
        precision (int): Decimals.

    Returns:
        float:
    """
    if isinstance(second, tuple):
        multiply = 10 ** precision
        result = random_normal_distribution_int(second[0] * multiply, second[1] * multiply, n) / multiply
        return round(result, precision)
    elif isinstance(second, str):
        if ',' in second:
            lower, upper = second.replace(' ', '').split(',')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        if '-' in second:
            lower, upper = second.replace(' ', '').split('-')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        else:
            return int(second)
    else:
        return second


def ensure_int(*args):
    """
    Convert all elements to int.
    Return the same structure as nested objects.

    Args:
        *args:

    Returns:
        list:
    """

    def to_int(item):
        try:
            return int(item)
        except TypeError:
            result = [to_int(i) for i in item]
            if len(result) == 1:
                result = result[0]
            return result

    return to_int(args)


def float2str(n, decimal=3):
    """
    Args:
        n (float):
        decimal (int):

    Returns:
        str:
    """
    return str(round(n, decimal)).ljust(decimal + 2, "0")


def point2str(x, y, length=4):
    """
    Args:
        x (int, float):
        y (int, float):
        length (int): Align length.

    Returns:
        str: String with numbers right aligned, such as '( 100,  80)'.
    """
    return '(%s, %s)' % (str(int(x)).rjust(length), str(int(y)).rjust(length))