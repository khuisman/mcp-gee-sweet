# Study Notes: Distributed Consensus

## 1. The problem

A group of nodes must agree on a single value, even if some nodes crash or
messages are delayed. Consensus is the core of replicated logs, leader election,
and distributed locks.

## 2. Key properties

- **Safety**: nodes never decide different values
- **Liveness**: nodes eventually decide
- **Fault tolerance**: works with up to *f* failures out of *2f + 1* nodes

## 3. Raft in brief

1. **Leader election**
   - Every node starts as a *follower*
   - A follower that hears nothing for an election timeout becomes a *candidate*
     and asks for votes
   - A candidate with a majority becomes the *leader*
2. **Log replication**
   - The leader appends client commands to its log
   - It sends `AppendEntries` to followers
   - An entry is *committed* once a majority stores it
3. **Safety rule**
   - A candidate can only win if its log is at least as up to date as a majority's

## 4. Paxos vs. Raft

| | Paxos | Raft |
|---|---|---|
| Designed for | Correctness proofs | Understandability |
| Leader | Optional (Multi-Paxos uses one) | Always |
| Typical use | Spanner, Chubby | etcd, Consul |

## 5. Quick math

With *n* = 5 nodes, a majority is ⌊5/2⌋ + 1 = **3**, so the cluster survives
2 failures. With *n* = 4, a majority is still 3, so it survives only 1 failure,
which is why odd cluster sizes are preferred.

## 6. Questions to review

1. Why can't a node with a stale log become leader?
2. What happens to uncommitted entries when a leader crashes?
3. How does Raft handle a network partition that isolates the leader?

## 7. Sources

- Ongaro & Ousterhout, *In Search of an Understandable Consensus Algorithm* (2014)
- Lamport, *Paxos Made Simple* (2001)
- https://raft.github.io/
