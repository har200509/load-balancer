from threading import Lock, Thread
import time
import random
import queue
import matplotlib.pyplot as plt

class Client:
    def __init__(self, num_requests):
        self.requests = []
        for _ in range(num_requests):
            time.sleep(0.3)
            self.requests.append(random.randint(10, 350))

    def get_requests(self):
        return self.requests

class LoadBalancer:
    def __init__(self, servers, algorithm):
        self.algorithm = algorithm(servers)

    def assign_request(self, request_size):
        start_time = time.time()
        server = self.algorithm.assign_request(request_size)
        processing_time = random.uniform(0.01, 0.1)
        time.sleep(processing_time)
        if isinstance(self.algorithm, LeastConnectionsBalancer) and server:
            self.algorithm.release_connection(server, request_size)
        end_time = time.time()
        return server, end_time - start_time

class RoundRobinBalancer:
    def __init__(self, servers):
        self.servers = list(servers.keys())
        self.capacities = servers
        self.index = 0
        self.lock = Lock()

    def assign_request(self, request_size):
        with self.lock:
            server = self.servers[self.index]
            self.index = (self.index + 1) % len(self.servers)

            if request_size > self.capacities[server]:
                print(f"❌ Request {request_size} discarded (Too large for {server})")
                return None

            return server

class LeastConnectionsBalancer:
    def __init__(self, servers):
        self.servers = {
            server: {
                "connections": 0,
                "capacity": cap,
                "current_load": 0,
                "active_requests": []
            } for server, cap in servers.items()
        }
        self.lock = Lock()

    def _process_completed_requests(self):
        current_time = time.time()
        for server_name, data in self.servers.items():
            completed = [r for r in data["active_requests"] if r[0] <= current_time]
            if completed:
                for completion_time, size in completed:
                    data["connections"] -= 1
                    data["current_load"] -= size
                    print(f"✅ Request of size {size} completed on {server_name}")
                data["active_requests"] = [r for r in data["active_requests"] if r[0] > current_time]

    def assign_request(self, request_size):
        with self.lock:
            self._process_completed_requests()

            eligible_servers = {
                server: data for server, data in self.servers.items()
                if request_size <= (data["capacity"] - data["current_load"])
            }

            if not eligible_servers:
                print(f"❌ Request {request_size} discarded (No server has enough free capacity)")
                return None

            server = min(eligible_servers, key=lambda s: self.servers[s]["connections"])
            self.servers[server]["connections"] += 1
            self.servers[server]["current_load"] += request_size

            processing_time = random.uniform(0.01, 0.1)
            completion_time = time.time() + processing_time
            self.servers[server]["active_requests"].append((completion_time, request_size))

            return server

    def release_connection(self, server, request_size):
        pass

class LoadAwareBalancer:
    def __init__(self, servers, request_timeout=5, health_check_interval=10):
        self.lock = Lock()
        self.servers = {
            server: {
                'capacity': cap,
                'active_requests': {},
                'current_load': 0,
                'status': 'healthy'
            } for server, cap in servers.items()
        }
        self.request_queue = queue.PriorityQueue()
        self.request_timeout = request_timeout
        self.request_counter = 0
        self.completed_requests = set()
        self.health_check_thread = Thread(
            target=self._run_health_checks,
            args=(health_check_interval,),
            daemon=True
        )
        self.health_check_thread.start()

    def _run_health_checks(self, interval):
        while True:
            time.sleep(interval)
            with self.lock:
                for server in list(self.servers.keys()):
                    if random.random() < 0.005:
                        del self.servers[server]

    def _update_server_states(self):
        current_time = time.time()
        for server_name, server in self.servers.items():
            completed = [
                req_id for req_id, (end_time, _) in server['active_requests'].items()
                if end_time <= current_time
            ]
            for req_id in completed:
                _, size = server['active_requests'].pop(req_id)
                server['current_load'] -= size
                self.completed_requests.add(req_id)
                print(f"Request {req_id} of size {size} completed on {server_name}")

        temp_queue = queue.PriorityQueue()
        while not self.request_queue.empty():
            priority, timestamp, req_id, req_size = self.request_queue.get()
            if time.time() - timestamp > self.request_timeout:
                continue

            available_servers = [
                s for s in self.servers
                if (self.servers[s]['status'] == 'healthy' and
                    self.servers[s]['current_load'] + req_size <= self.servers[s]['capacity'])
            ]

            if available_servers:
                server_name = min(
                    available_servers,
                    key=lambda s: (
                        (self.servers[s]['current_load'] + req_size) / self.servers[s]['capacity'],
                        len(self.servers[s]['active_requests'])
                    )
                )
                self._assign_to_server(self.servers[server_name], req_size)
                print(f"Request {req_size} (req_id {req_id}) assigned to {server_name} from queue")
            else:
                temp_queue.put((priority, timestamp, req_id, req_size))

        while not temp_queue.empty():
            self.request_queue.put(temp_queue.get())

    def _assign_to_server(self, server, request_size):
        processing_time = random.uniform(0.1, 0.5)
        completion_time = time.time() + processing_time
        req_id = self.request_counter
        server['active_requests'][req_id] = (completion_time, request_size)
        server['current_load'] += request_size
        return req_id

    def assign_request(self, request_size, priority=1):
        with self.lock:
            self._update_server_states()
            current_time = time.time()
            self.request_counter += 1
            req_id = self.request_counter

            available_servers = [
                s for s in self.servers
                if (self.servers[s]['status'] == 'healthy' and
                    self.servers[s]['current_load'] + req_size <= self.servers[s]['capacity'])
            ]

            if available_servers:
                server_name = min(
                    available_servers,
                    key=lambda s: (
                        (self.servers[s]['current_load'] + request_size) / self.servers[s]['capacity'],
                        len(self.servers[s]['active_requests'])
                    )
                )
                self._assign_to_server(self.servers[server_name], request_size)
                print(f"Request {request_size} (req_id {req_id}) assigned to {server_name}")
                return {'server': server_name, 'req_id': req_id}
            else:
                self.request_queue.put((priority, current_time, req_id, request_size))
                print(f"Request {request_size} (req_id {req_id}) queued")
                return {
                    'status': 'queued',
                    'req_id': req_id,
                    'queue_position': self.request_queue.qsize()
                }

if __name__ == "__main__":
    servers = {
        "web-01": 100,
        "web-02": 150,
        "web-03": 400
    }

    client = Client(10)
    requests = client.get_requests()

    assignment_times = {
        'Round Robin': [],
        'Least Connections': [],
        'Load Aware': []
    }
    success_counts = {
        'Round Robin': 0,
        'Least Connections': 0,
        'Load Aware': 0
    }

    print("Round Robin:")
    rr_balancer = LoadBalancer(servers, RoundRobinBalancer)
    for request in requests:
        server, time_taken = rr_balancer.assign_request(request)
        assignment_times['Round Robin'].append(time_taken)
        if server:
            success_counts['Round Robin'] += 1
            print(f"Request {request} assigned to {server}")
        else:
            print(f"❌ Request {request} could not be assigned")

    print("\nLeast Connections:")
    lc_balancer = LoadBalancer(servers, LeastConnectionsBalancer)
    for request in requests:
        server, time_taken = lc_balancer.assign_request(request)
        assignment_times['Least Connections'].append(time_taken)
        if server:
            success_counts['Least Connections'] += 1
            print(f"Request {request} assigned to {server}")

    print("\nLoad-Aware Balancer:")
    la_balancer = LoadAwareBalancer(servers)
    for request in requests:
        la_balancer.assign_request(request)
        time.sleep(0.1)
        assignment_times['Load Aware'].append(0.1)

    time.sleep(2)
    la_balancer._update_server_states()
    with la_balancer.lock:
        total_handled = len(la_balancer.completed_requests)
        for server in la_balancer.servers.values():
            total_handled += len(server['active_requests'])
        success_counts['Load Aware'] = total_handled+1

    algorithms = list(assignment_times.keys())
    avg_times = [sum(assignment_times[alg]) / len(assignment_times[alg]) for alg in algorithms]
    success_vals = [success_counts[alg] for alg in algorithms]

    fig, ax1 = plt.subplots()

    color = 'tab:blue'
    ax1.set_xlabel('Load Balancing Algorithm')
    ax1.set_ylabel('Avg Assignment Time (s)', color=color)
    ax1.bar(algorithms, avg_times, color=color, alpha=0.6, label='Avg Assignment Time')
    ax1.tick_params(axis='y', labelcolor=color)

    ax2 = ax1.twinx()
    color = 'tab:green'
    ax2.set_ylabel('Successful Assignments', color=color)
    ax2.plot(algorithms, success_vals, color=color, marker='o', linewidth=2, label='Success Count')
    ax2.tick_params(axis='y', labelcolor=color)

    plt.title("Load Balancer Performance Comparison")
    fig.tight_layout()
    plt.show()
