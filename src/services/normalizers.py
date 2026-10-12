# src/services/normalizers.py
from typing import Dict
from services.llm_client import llm


def build_search_normalize_prompt(
    filter_options: Dict[str, list[str]],
    inputs: Dict[str, str],
) -> str:
    """
    建立查詢格式轉換的prompt
    """
    return f'''
    你是一個查詢格式轉換器，只負責將使用者輸入的篩選條件和問題，轉換成查詢格式。

    限制的查詢欄位與對應欄位的值：
    - 委員名字：{filter_options['member_names']}
    - 涵蓋層級：{filter_options['geographical_scopes']}
    - 所屬委員會：{filter_options['committees']}
    
    請嚴格遵守以下規則：
    1. 只能根據「使用者輸入的篩選條件」與「使用者問題」判斷查詢值。
    2. 所有欄位都必須輸出（即使為 all）。
    3. 若輸入的篩選條件不在允許的範圍內，一律改為 all。
    4. 只能根據限制的查詢欄位與對應欄位的值，不能自由發揮輸出限制以外的文字。
    5. 回答中禁止加上任何說明、評論或重複問題，**只輸出條件語法**。
    
    ---
    
    以下是範例：
    
    example1:
    使用者輸入的篩選條件: 委員名字: all、涵蓋層級: 地方、所屬委員會: 交通委員會
    使用者問題: 4月交通委員會談網路詐騙的是哪位立委？
    回答: 委員名字:all、涵蓋層級:地區性、所屬委員會:交通委員會
    
    example2:
    使用者輸入的篩選條件: 委員名字: 育敏、涵蓋層級: all、所屬委員會: all
    使用者問題: 2025年3月17日育敏對學童營養午餐有什麼看法？
    回答: 委員名字:王育敏、涵蓋層級:all、所屬委員會:all
    
    example3:
    使用者輸入的篩選條件: 委員名字: 天財和若華、涵蓋層級: all、所屬委員會: all
    使用者問題: 4~5月交通委員會討論網路詐騙時，這兩位立委分別主張了什麼？
    回答: 委員名字:鄭天財、委員名字:邱若華、涵蓋層級:all、所屬委員會:交通委員會

    example4:
    使用者輸入的篩選條件: 委員名字: all、涵蓋層級: all、所屬委員會: 內政、交通
    使用者問題: 這兩個委員會在2025年1月有多少次發言?
    回答: 委員名字:all、涵蓋層級:all、所屬委員會:內政委員會、所屬委員會:交通委員會
    
    ---

    使用者輸入的篩選條件: 委員名字: {inputs["委員名字"]}、涵蓋層級: {inputs["涵蓋層級"]}、所屬委員會: {inputs["所屬委員會"]} 
    使用者問題: {inputs["問題"]}  
    回答：
    '''

def normalize_filters_with_llm(
    filter_options: Dict[str, list[str]],
    inputs: Dict[str, str],
) -> str:
    """
    使用 LLM 轉換使用者輸入的篩選條件和問題為查詢格式
    """
    prompt = build_search_normalize_prompt(filter_options, inputs)
    search_answer = llm.invoke(prompt)
    unprocessed_search_answer = getattr(search_answer, "content", str(search_answer))
    return unprocessed_search_answer
