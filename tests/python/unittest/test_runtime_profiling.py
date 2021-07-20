# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import numpy as np
import pytest
from io import StringIO
import csv
import os

import tvm.testing
from tvm.runtime import profiler_vm
from tvm import relay
from tvm.relay.testing import mlp
from tvm.contrib.debugger import debug_executor


def read_csv(report):
    f = StringIO(report.csv())
    headers = []
    rows = []
    reader = csv.reader(f, delimiter=",")
    # force parsing
    in_header = True
    for row in reader:
        if in_header:
            headers = row
            in_header = False
            rows = [[] for x in headers]
        else:
            for i in range(len(row)):
                rows[i].append(row[i])
    return dict(zip(headers, rows))


@pytest.mark.skipif(not profiler_vm.enabled(), reason="VM Profiler not enabled")
@tvm.testing.parametrize_targets
def test_vm(target, dev):
    mod, params = mlp.get_workload(1)

    exe = relay.vm.compile(mod, target, params=params)
    vm = profiler_vm.VirtualMachineProfiler(exe, dev)

    data = np.random.rand(1, 1, 28, 28).astype("float32")
    report = vm.profile(data, func_name="main")
    assert "fused_nn_softmax" in str(report)
    assert "Total" in str(report)

    csv = read_csv(report)
    assert "Hash" in csv.keys()
    assert all([float(x) > 0 for x in csv["Duration (us)"]])


@tvm.testing.parametrize_targets
def test_graph_executor(target, dev):
    mod, params = mlp.get_workload(1)

    exe = relay.build(mod, target, params=params)
    gr = debug_executor.create(exe.get_graph_json(), exe.lib, dev)

    data = np.random.rand(1, 1, 28, 28).astype("float32")
    report = gr.profile(data=data)
    assert "fused_nn_softmax" in str(report)
    assert "Total" in str(report)
    assert "Hash" in str(report)


@tvm.testing.parametrize_targets("cuda", "llvm")
@pytest.mark.skipif(
    tvm.get_global_func("runtime.profiling.PAPIMetricCollector", allow_missing=True) is None,
    reason="PAPI profiling not enabled",
)
def test_papi(target, dev):
    target = tvm.target.Target(target)
    if str(target.kind) == "llvm":
        metric = "PAPI_FP_OPS"
    elif str(target.kind) == "cuda":
        metric = "cuda:::event:shared_load:device=0"
    else:
        pytest.skip(f"Target {target.kind} not supported by this test")
    mod, params = mlp.get_workload(1)

    exe = relay.vm.compile(mod, target, params=params)
    vm = profiler_vm.VirtualMachineProfiler(exe, dev)

    data = tvm.nd.array(np.random.rand(1, 1, 28, 28).astype("float32"), device=dev)
    report = vm.profile(
        [data],
        func_name="main",
        collectors=[tvm.runtime.profiling.PAPIMetricCollector({dev: [metric]})],
    )
    print(report)
    assert metric in str(report)

    csv = read_csv(report)
    assert metric in csv.keys()
    assert any([float(x) > 0 for x in csv[metric]])


if __name__ == "__main__":
    test_papi("llvm", tvm.cpu())
