import re
import sys
import os
import bisect
import json
import hashlib
import xml.etree.ElementTree as ET

# Настройка кодировки вывода для корректного отображения кириллицы в консоли
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

CACHE_FILE = ".bsl_cache.json"

def calculate_md5(file_path):
    """
    Вычисляет MD5-хеш файла по пути file_path.
    """
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось вычислить MD5 для '{file_path}': {e}")
        return ""

def load_cache(cache_path):
    """
    Загружает кэш хешей файлов из JSON-файла.
    """
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось загрузить кэш из '{cache_path}': {e}")
    return {}

def save_cache(cache_path, cache_data):
    """
    Сохраняет кэш хешей файлов в JSON-файл.
    """
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
        print(f"[ИНФО] Кэш сохранен в '{cache_path}'")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось сохранить кэш в '{cache_path}': {e}")

def read_file_with_encoding(file_path):
    """
    Пытается прочитать файл в кодировке utf-8-sig (для обработки BOM) с откатом на cp1251.
    """
    for enc in ['utf-8-sig', 'utf-8', 'cp1251']:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
            return content, enc
        except UnicodeDecodeError:
            continue
    
    # Чтение с заменой нераспознанных символов в случае ошибки
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    return content, 'utf-8-replace'

def clean_comment_line(line):
    """
    Удаляет начальные '//' и до одного пробела после них.
    """
    return re.sub(r'^//[ \t]?', '', line)

def get_module_synonym(xml_path):
    """
    Разбирает XML-файл метаданных модуля для извлечения синонима на русском языке (ru).
    """
    if not os.path.exists(xml_path):
        return ""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Поиск тега <item> без учета пространства имен, затем поиск <lang>ru</lang> и соседнего <content>
        for item in root.iter():
            if item.tag.endswith('item'):
                lang_node = None
                content_node = None
                for child in item:
                    if child.tag.endswith('lang'):
                        lang_node = child
                    elif child.tag.endswith('content'):
                        content_node = child
                if lang_node is not None and content_node is not None:
                    if lang_node.text == 'ru':
                        return content_node.text.strip()
                        
        # Резервный вариант: если нет явного элемента 'ru', найти первый элемент 'content' с текстом
        for item in root.iter():
            if item.tag.endswith('content') and item.text:
                return item.text.strip()
    except Exception as e:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось распарсить XML '{xml_path}': {e}")
    return ""

def parse_bsl_module(file_path):
    """
    Разбирает один BSL-файл для извлечения экспортных процедур/функций и их комментариев.
    """
    content, _ = read_file_with_encoding(file_path)
    
    # Разбиение содержимого на строки для извлечения комментариев
    lines = content.split('\n')
    line_offsets = []
    current_offset = 0
    for line in lines:
        line_offsets.append(current_offset)
        current_offset += len(line) + 1
        
    pattern = re.compile(
        r'(?im)^[ \t]*(?P<type>процедура|функция|procedure|function)\s+(?P<name>[a-zA-Zа-яА-Я_0-9]+)\s*\((?P<params>[^)]*)\)\s*(?P<export>экспорт|export)\b'
    )
    
    methods = []
    
    for match in pattern.finditer(content):
        name = match.group('name')
        method_type = match.group('type')
        signature = match.group(0).strip()
        start_offset = match.start()
        
        # Определение индекса строки, с которой начинается метод
        line_idx = bisect.bisect_right(line_offsets, start_offset) - 1
        
        # Сбор предшествующих комментариев
        comment_lines = []
        for idx in range(line_idx - 1, -1, -1):
            curr_line = lines[idx].strip()
            if curr_line.startswith('//'):
                comment_lines.append(lines[idx])
            else:
                break
                
        comment_lines.reverse()
        
        cleaned_comments = [clean_comment_line(line) for line in comment_lines]
        
        while cleaned_comments and not cleaned_comments[0].strip():
            cleaned_comments.pop(0)
        while cleaned_comments and not cleaned_comments[-1].strip():
            cleaned_comments.pop()
            
        description = "\n".join(cleaned_comments).strip()
        if not description:
            description = "Описание отсутствует"
            
        methods.append({
            'name': name,
            'type': method_type.capitalize(),
            'signature': signature,
            'description': description
        })
        
    return methods

def generate_module_markdown(module_name, synonym, methods, output_path):
    """
    Генерирует Markdown-файл документации для одного общего модуля.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Модуль {module_name}\n\n")
            if synonym:
                f.write(f"**Описание подсистемы:** {synonym}\n\n")
            f.write(f"Всего найдено экспортных методов: **{len(methods)}**\n\n")
            
            if not methods:
                f.write("Экспортные методы в данном модуле отсутствуют.\n")
                return
                
            f.write("## Список методов\n\n")
            for m in methods:
                f.write(f"- [{m['name']}](#{m['name'].lower()}) ({m['type']})\n")
            f.write("\n---\n\n")
            
            for m in methods:
                f.write(f"### <a name=\"{m['name'].lower()}\"></a>{m['name']}\n\n")
                f.write(f"- **Тип:** {m['type']}\n")
                f.write("- **Сигнатура:**\n")
                f.write("  ```bsl\n")
                signature_indented = "\n  ".join(m['signature'].split('\n'))
                f.write(f"  {signature_indented}\n")
                f.write("  ```\n")
                f.write("- **Описание:**\n\n")
                desc_lines = m['description'].split('\n')
                formatted_desc = "\n".join([f"  {line}" if line else "" for line in desc_lines])
                f.write(f"{formatted_desc}\n\n")
                f.write("---\n\n")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось записать markdown модуля '{output_path}': {e}")

def main():
    config_path = "ConfigFiles"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        
    docs_dir = "docs"
    manifest_path = "llms.txt"
    cache_path = os.path.join(os.getcwd(), CACHE_FILE)
    
    common_modules_dir = os.path.join(config_path, "CommonModules")
    if not os.path.exists(common_modules_dir):
        print(f"[ОШИБКА] Папка CommonModules не найдена по пути '{common_modules_dir}'.")
        sys.exit(1)
        
    print(f"[ИНФО] Сканирование '{common_modules_dir}' на наличие модулей...")
    
    modules = []
    
    # 1. Обход всех элементов в CommonModules
    for item in os.listdir(common_modules_dir):
        item_path = os.path.join(common_modules_dir, item)
        if os.path.isdir(item_path):
            module_name = item
            
            # Рекурсивный поиск всех файлов .bsl внутри папки модуля
            bsl_files = []
            for root, dirs, files in os.walk(item_path):
                for file in files:
                    if file.lower().endswith('.bsl'):
                        bsl_files.append(os.path.join(root, file))
            
            if not bsl_files:
                continue
                
            bsl_path = bsl_files[0]
            xml_path = os.path.join(common_modules_dir, f"{module_name}.xml")
            
            modules.append({
                'name': module_name,
                'bsl_path': bsl_path,
                'xml_path': xml_path
            })
            
    # Сортировка модулей по алфавиту
    modules.sort(key=lambda x: x['name'])
    
    # Загрузка старого кэша
    cache = load_cache(cache_path)
    
    processed_modules = []
    cache_hits = 0
    parsed_count = 0
    
    print(f"[ИНФО] Найдено {len(modules)} общих модулей с файлами кода. Обработка...")
    
    # 2. Обработка каждого модуля с использованием кэша
    for idx, mod in enumerate(modules, 1):
        module_name = mod['name']
        bsl_path = mod['bsl_path']
        xml_path = mod['xml_path']
        
        # Получение синонима/описания из XML
        synonym = get_module_synonym(xml_path)
        display_desc = synonym if synonym else f"Общий модуль {module_name}"
        display_desc_clean = display_desc.replace('\n', ' ').strip()
        
        # Путь к итоговому markdown-файлу
        relative_doc_path = f"docs/common_modules/{module_name}.md"
        absolute_doc_path = os.path.join(os.getcwd(), relative_doc_path)
        
        # Расчет текущего хеша
        current_hash = calculate_md5(bsl_path)
        
        # Определение возможности использования кэша
        doc_exists = os.path.exists(absolute_doc_path)
        cached_hash = cache.get(module_name)
        
        if doc_exists and cached_hash == current_hash:
            print(f"[КЭШ] Модуль '{module_name}' не изменился. Пропуск.")
            cache_hits += 1
        else:
            reason = "изменен" if doc_exists else "отсутствует документация"
            print(f"[РАЗОБРАН] Модуль '{module_name}' ({reason}). Пересборка...")
            methods = parse_bsl_module(bsl_path)
            generate_module_markdown(module_name, synonym, methods, absolute_doc_path)
            cache[module_name] = current_hash
            parsed_count += 1
            
        processed_modules.append({
            'name': module_name,
            'doc_path': relative_doc_path,
            'description': display_desc_clean
        })
        
    print(f"[ИНФО] Обработка завершена. Попаданий в кэш: {cache_hits}, Заново разобрано: {parsed_count}")
    
    # 3. Генерация корневого файла-манифеста llms.txt
    try:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write("# Путеводитель по конфигурации\n\n")
            f.write("> Автоматически сгенерированный путеводитель по экспортным методам общих модулей конфигурации 1С.\n\n")
            f.write("## Общие модули\n\n")
            
            for p_mod in processed_modules:
                f.write(f"- [{p_mod['name']}]({p_mod['doc_path']}): {p_mod['description']}.\n")
                
        print(f"[ИНФО] Корневой манифест успешно сгенерирован: '{manifest_path}'")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось записать файл манифеста '{manifest_path}': {e}")
        sys.exit(1)
        
    # 4. Сохранение обновленного кэша в самом конце
    save_cache(cache_path, cache)

if __name__ == "__main__":
    main()
