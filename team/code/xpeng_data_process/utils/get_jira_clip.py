import requests
import json
import argparse
import datetime
import os

def is_daytime_in_china(timestamp):
    # 将时间戳转换为秒，因为 Python 的 datetime 模块通常使用秒级时间戳
    timestamp_seconds = timestamp / 1e9
    # 创建 datetime 对象，假设时间戳是 UTC 时间
    utc_time = datetime.datetime.utcfromtimestamp(timestamp_seconds)
    # 定义中国所在的时区（东八区，UTC+8）
    china_timezone = datetime.timezone(datetime.timedelta(hours=8))
    # 将 UTC 时间转换为中国时区的时间
    china_time = utc_time.replace(tzinfo=datetime.timezone.utc).astimezone(china_timezone)
    # 获取中国时间的小时部分
    hour = china_time.hour
    # 判断是否为白天，这里简单假设 6 点到 18 点为白天
    if 8 <= hour < 18:
        return True
    return False


def get_jira_name_accroding_label(num, label):
    jira_list = []
    data = {
        'page': 1,
        'size': num,
        'search_labels': 'xlidc,xdds_transcoded',
        'type': 48,
        'status': -1,
        'userName': 'lvy10@xiaopeng.com',
        'search_labels': label
    }
    req = requests.post('http://cloudsim.xiaopeng.link/simulation/scenario/paginate_query_aio/', data=data)
    data = json.loads(req.text)
    # print(f"jira name: {data}")
    
    for info in data["data"]:
        scenario = json.loads(info["scenario"])
        startTimestamp = scenario["tripSegment"]["startTimestamp"]
        if is_daytime_in_china(startTimestamp):
            input_string = info["name"]
            parts = input_string.split("_")
            result = parts[0].strip("[]")
            jira_list.append(result)
            print(f"{result} is daytime {startTimestamp}")
            
    return jira_list


def get_clip_ids(jira_list):
    jira_2_clip = {}
    for jira_id in jira_list:
        data = {"query":{"bool":{"should":[{"match_phrase":{"issues.jira_id":jira_id}}],"must_not":[{"term":{"generic_tag.retention.tags":"deleted"}}],"minimum_should_match":1}},"size":1,"aggs":{"prefix":{"terms":{"field":"prefix","size":4999,"order":{"_key":"desc"}},"aggs":{"by_top_hits":{"top_hits":{"sort":[{"seq_num":{"order":"asc"}}],"size":100}},"city":{"terms":{"field":"city"}},"bucket_truncate":{"bucket_sort":{"from":0,"size":10}}}}},"sort":[{"seq_num":"asc"}]}
        rsp = requests.post("http://kb_reader:Kb0109@es-cn-nwy340rdt000b4pzh.public.elasticsearch.aliyuncs.com:9200/dds-clip-fullstack/_search", data=json.dumps(data), headers={'Content-Type': 'application/json'})
        rsp_data = json.loads(rsp.text)
        # print(f"xxx jira_id: {jira_id}")
        # print(f"xxx rsp_data: {rsp_data}")


        for buckets in rsp_data['aggregations']['prefix']['buckets']:
            clip_list = []
            for hits in buckets['by_top_hits']['hits']['hits']:
                clip_list.append(hits['_source']['raw_clip_id'])
                print(hits['_source']['raw_clip_id'])
        jira_2_clip[jira_id] = clip_list
    print(f"jira_2_clip: {jira_2_clip}")
    return jira_2_clip


def get_clip_ids_subrun_ids(jira_list):
    print(f"jira_list size {len(jira_list)} ")
    not_found_size = 0
    found_size = 0
    jira_2_clip = {"h265-subrun-portal-latest":{},"master-subrun-portal-latest":{}}
    search_sourch = ""
    for jira_id in jira_list: 
        data = {
        "query": {
            "bool": {
            "should": [
                {
                "match_phrase": {
                    "jira_id": jira_id
                }
                }
            ],
            "minimum_should_match": 1
            }
        },
        "size": 20,
        "sort": [
            {
            "id": "desc"
            }
        ],
        } 
        rsp = requests.post("http://kb_reader:Kb0109@es-cn-nwy340rdt000b4pzh.public.elasticsearch.aliyuncs.com:9200/h265-subrun-portal-latest/_search", data=json.dumps(data), headers={'Content-Type': 'application/json'})
        rsp_data = json.loads(rsp.text)
        search_sourch = "h265-subrun-portal-latest"
        clip_list = []
        subrun_id = ""
        # print(f"rsp_data {rsp_data}")
        if not rsp_data.get('hits',None):
            continue
        if not rsp_data['hits'].get('hits',None):
            not_found_size+=1
            print(f"{jira_id} can not be searched in h265-subrun-portal-latest")
            rsp = requests.post("http://kb_reader:Kb0109@es-cn-nwy340rdt000b4pzh.public.elasticsearch.aliyuncs.com:9200/master-subrun-portal-latest/_search", data=json.dumps(data), headers={'Content-Type': 'application/json'})
            rsp_data = json.loads(rsp.text)
            search_sourch = "master-subrun-portal-latest"
            
            if not rsp_data['hits']['hits']:
                print(f"!!!Warning {jira_id} can not be searched")
                continue
            else:
                print(f"now {jira_id} can be searched in master-subrun-portal-latest")
        # print(f"rsp_data {rsp_data['hits']['hits']}")

        has_clip=False
        jira_2_info={}
        for hits in rsp_data['hits']['hits']:
            found_size+=1
            subrun_id = hits['_source']['id']
            print(subrun_id)
            if 'lidarm1' not in hits['_source']['lidar_sensor_type']:
                print(f"warning {jira_id} lost lidarm1")
                continue
            event_trigger_time = hits['_source']['event_trigger_time']
            Vehicle_model = hits['_source']["event_build_version"]['Vehicle_model']
            for clip_id in hits['_source']['clip_id_list']:
                has_clip = True
                clip_list.append(clip_id)
                print(clip_id)
        if has_clip:
            jira_2_clip[search_sourch][jira_id]={"subrun_id":subrun_id,"clip_list":clip_list,"event_trigger_time":event_trigger_time,"Vehicle_model":Vehicle_model}
    # print(f"jira_2_clip: {jira_2_clip}")
    print(f"not_found_size size {not_found_size} ")
    print(f"found_size size {found_size} ")
    
    return jira_2_clip
        

# command:  python3 /home/lvy10/repo/simworld/xpeng_data_process/utils/get_jira_clip.py --mode=acoording_label --input_list=/home/lvy10/repo/input_list.json --out_putpath=/home/lvy10/repo/

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Evaluator',
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        '--jira_size',
        required=False,
        help='jira size'
    )
    parser.add_argument(
        '--mode',
        required=False,
        help='according label or jira list'
    )
    
    parser.add_argument(
        '--input_list',
        required=False,
        help='according label or jira list'
    )
    parser.add_argument(
        '--out_putpath',
        required=False,
        help='jira to clip result json path'
    )
    args = parser.parse_args()
    with open(args.input_list, 'r') as json_file:
        input_list = json.load(json_file)
        
    if args.mode == "acoording_label":
        label_list = ""
        for info in input_list["label_list"]:
            label_list += info
            if info !=input_list["label_list"][-1]:
                label_list+=','
        label = f'(({label_list}),(planning_must_pass|planning_should_pass|planning_maybe_pass))'
        jira_list = get_jira_name_accroding_label(input_list['jira_size'], label)
        print(f"jira_list {jira_list}")
        jira_2_clip = get_clip_ids_subrun_ids(jira_list)

        with open(os.path.join(args.out_putpath,"jira_2_clip.json"), 'w') as json_file:
            json.dump(jira_2_clip, json_file, indent=4)
    elif args.mode == "acoording_jira_list":
        print(f"jira_list {input_list}")
        jira_2_clip = get_clip_ids_subrun_ids(input_list)

        with open(os.path.join(args.out_putpath,"jira_2_clip.json"), 'w') as json_file:
            json.dump(jira_2_clip, json_file, indent=4)