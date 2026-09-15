package main

import (
	"bytes"
	"net"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

const AgentVersion = "1.0.0"

var SecretToken = os.Getenv("API_TOKEN")

type PeerTraffic struct {
	PublicKey  string `json:"pub"`
	Rx         int64  `json:"rx"`
	Tx         int64  `json:"tx"`
	Handshake  int64  `json:"handshake"`
	EndpointIP string `json:"endpoint_ip"`
}

type ServerHealth struct {
	LoadAvg   float64 `json:"load_avg"`
	MemFreeMB int64   `json:"mem_free_mb"`
}

type LoadResponse struct {
	ServerVersion string        `json:"server_version"`
	Health        ServerHealth  `json:"health"`
	Peers         []PeerTraffic `json:"peers"`
}

func getServerHealth() ServerHealth {
	var health ServerHealth

	if data, err := os.ReadFile("/proc/loadavg"); err == nil {
		fields := strings.Fields(string(data))
		if len(fields) > 0 {
			health.LoadAvg, _ = strconv.ParseFloat(fields[0], 64)
		}
	}

	if data, err := os.ReadFile("/proc/meminfo"); err == nil {
		lines := strings.Split(string(data), "\n")
		for _, line := range lines {
			if strings.HasPrefix(line, "MemAvailable:") {
				fields := strings.Fields(line)
				if len(fields) >= 2 {
					kb, _ := strconv.ParseInt(fields[1], 10, 64)
					health.MemFreeMB = kb / 1024
				}
				break
			}
		}
	}

	return health
}

func getAWGLoad(interfaceName string) ([]PeerTraffic, error) {
	cmd := exec.Command("awg", "show", interfaceName, "dump")
	var out bytes.Buffer
	cmd.Stdout = &out

	if err := cmd.Run(); err != nil {
		return nil, err
	}

	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) <= 1 {
		return []PeerTraffic{}, nil
	}

	peers := make([]PeerTraffic, 0, len(lines)-1)

	for _, line := range lines[1:] {
		fields := strings.Split(line, "\t")
		if len(fields) < 8 {
			continue
		}

		rx, _ := strconv.ParseInt(fields[5], 10, 64)
		tx, _ := strconv.ParseInt(fields[6], 10, 64)
		handshake, _ := strconv.ParseInt(fields[4], 10, 64)

		rawEndpoint := fields[2]
		endpointIP := ""
		if rawEndpoint != "(none)" {
			host, _, err := net.SplitHostPort(rawEndpoint)
			if err == nil {
				endpointIP = host
			} else {
				endpointIP = rawEndpoint
			}
		}

		if rx > 0 || tx > 0 || handshake > 0 {
			peers = append(peers, PeerTraffic{
				PublicKey:  fields[0],
				Rx:         rx,
				Tx:         tx,
				Handshake:  handshake,
				EndpointIP: endpointIP,
			})
		}
	}

	return peers, nil
}

func main() {
	gin.SetMode(gin.ReleaseMode)
	r := gin.Default()

	r.GET("/api/v1/load", func(c *gin.Context) {
		clientToken := c.GetHeader("X-API-Token")
		if clientToken != SecretToken {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Unauthorized access"})
			return
		}

		serverID := c.Query("server")
		if serverID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "server parameter is required"})
			return
		}

		peers, err := getAWGLoad("wg-" + serverID)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		response := LoadResponse{
			ServerVersion: AgentVersion,
			Health:        getServerHealth(),
			Peers:         peers,
		}

		c.JSON(http.StatusOK, response)
	})

	if err := r.Run(":8081"); err != nil {
		panic(err)
	}
}
